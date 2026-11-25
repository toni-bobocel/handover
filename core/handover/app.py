import asyncio
import contextlib
import json
import logging
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import fleet as fleet_mod
from .adapters import Unsupported
from .adapters.rest import Rest
from .blackbox import Recorder
from .blackbox.bundle import load_key
from .bus import Bus
from .geofence import Guard, Zone
from .model import Event, Status, Telemetry
from .rules import Limits, Watcher
from .store import Store
from .teleop import MAX_ANGULAR, MAX_LINEAR, Busy, Teleop

log = logging.getLogger("handover")

# events that are an operator's or a rule's doing, kept beyond the ring for the audit trail
AUDITED = {"takeover", "released", "deadman_stop", "operator_lost", "zone_stop", "zone_warning",
           "estop", "needs_assistance", "link_lost", "battery_low", "paused", "resumed"}


def create(config_path: Path) -> FastAPI:
    cfg = fleet_mod.load(config_path)
    bus = Bus()
    fleet = fleet_mod.Fleet(cfg.robots, bus)
    store = Store(cfg.data / "handover.db")
    for z in cfg.zones:
        if not any(s["id"] == z["id"] for s in store.zones()):
            store.put_zone(z)
    key = load_key(cfg.data / "site.key")
    r = cfg.rules
    recorder = Recorder(bus, store, key, cfg.data / "incidents", cfg.site,
                        before=r.get("before", 30), after=r.get("after", 30))
    watcher = Watcher(bus, fleet, Limits(
        battery_low=r.get("battery_low", 0.10),
        link_lost_after=r.get("link_lost_after", 3.0),
        blocked_after=r.get("blocked_after", 15.0),
    ))
    teleop = Teleop(bus, fleet)
    guard = Guard(bus, fleet, [Zone.parse(z) for z in store.zones()], is_driven=teleop.driving)

    def shown(t: Telemetry) -> dict:
        d = t.as_dict()
        if teleop.driving(t.robot):
            d["status"] = Status.TELEOP
        elif watcher.assisting(t.robot) and t.status == Status.OK:
            d["status"] = Status.NEEDS_ASSISTANCE
        return d

    async def audit() -> None:
        async with bus.subscribe() as q:
            while True:
                m = await q.get()
                if isinstance(m, Event) and m.kind in AUDITED:
                    store.audit(m.t, m.robot, m.kind, m.detail)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = [asyncio.create_task(c) for c in (
            *(a.run() for a in fleet.values()), recorder.run(), watcher.run(), guard.run(), audit(),
        )]
        log.info("%s: %d robots, %d zones", cfg.site, len(fleet), len(guard.zones))
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="handover", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")

    def robot(id: str):
        if id not in fleet:
            raise HTTPException(404, f"no robot {id}")
        return fleet[id]

    @app.get("/api/site")
    def site():
        return {"name": cfg.site, "plan": cfg.plan, "robots": fleet.describe(), "zones": list(guard.zones.values()),
                "demo": bool(cfg.sim_url)}

    @app.get("/api/incidents")
    def incidents():
        return store.incidents()

    @app.get("/api/incidents/{id}/bundle")
    def download(id: str):
        inc = store.incident(id)
        if not inc or not inc["bundle"]:
            raise HTTPException(404, "not sealed yet")
        return FileResponse(cfg.data / "incidents" / inc["bundle"], media_type="application/zip",
                            filename=inc["bundle"])

    @app.get("/api/site.pub")
    def public_key():
        return FileResponse(cfg.data / "site.pub", media_type="application/x-pem-file", filename="site.pub")

    @app.post("/api/robots/{id}/pause")
    async def pause(id: str):
        await robot(id).pause()
        bus.publish(Event("paused", id, {"by": "operator"}))

    @app.post("/api/robots/{id}/resume")
    async def resume(id: str):
        await robot(id).resume()
        bus.publish(Event("resumed", id, {"by": "operator"}))

    @app.post("/ingest/{id}")
    async def ingest(id: str, request: Request):
        a = robot(id)
        if not isinstance(a, Rest):
            raise HTTPException(409, f"{id} does not report over REST")
        a.ingest(await request.json())
        return {"ok": True}

    @app.put("/api/zones/{id}")
    async def put_zone(id: str, body: dict):
        z = Zone.parse({**body, "id": id})
        if len(z.polygon) < 3:
            raise HTTPException(422, "a zone needs at least three corners")
        store.put_zone({**body, "id": id})
        guard.zones[id] = z
        bus.publish(Event("zone_changed", "*", {"id": id}))
        return z

    @app.delete("/api/zones/{id}")
    async def delete_zone(id: str):
        store.delete_zone(id)
        guard.zones.pop(id, None)
        bus.publish(Event("zone_changed", "*", {"id": id}))

    @app.post("/api/demo/{id}/{kind}")
    async def demo(id: str, kind: str):
        if not cfg.sim_url:
            raise HTTPException(404, "not a demo site")
        robot(id)
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.post(f"{cfg.sim_url}/incident", json={"robot": id, "kind": kind})
        if r.status_code >= 400:
            raise HTTPException(r.status_code, r.text)

    @app.websocket("/api/stream")
    async def stream(ws: WebSocket):
        await ws.accept()
        async with bus.subscribe() as q:
            try:
                while True:
                    m = await q.get()
                    if isinstance(m, Telemetry):
                        await ws.send_text(json.dumps({"type": "telemetry", **shown(m)}))
                    else:
                        await ws.send_text(json.dumps({"type": "event", **m.as_dict()}))
            except WebSocketDisconnect:
                pass

    @app.websocket("/api/teleop/{id}")
    async def drive(ws: WebSocket, id: str):
        await ws.accept()
        operator = ws.query_params.get("operator") or (ws.client.host if ws.client else "unknown")
        try:
            robot(id)
            await teleop.take(id, operator)
        except (HTTPException, Unsupported, Busy) as e:
            await ws.close(code=4409, reason=str(getattr(e, "detail", e))[:120])
            return
        limits = {"linear": MAX_LINEAR, "angular": MAX_ANGULAR}
        await ws.send_text(json.dumps({"type": "granted", "robot": id, "limits": limits}))
        try:
            while True:
                m = json.loads(await ws.receive_text())
                if m.get("type") == "release":
                    await teleop.release(id)
                    await ws.close()
                    return
                twist = await teleop.command(id, float(m.get("linear", 0)), float(m.get("angular", 0)))
                await ws.send_text(json.dumps({"type": "ack", "linear": twist.linear, "angular": twist.angular,
                                               "t": time.time()}))
        except WebSocketDisconnect:
            # the dead-man switch has already stopped it, or will within 250 ms
            teleop.lost(id)

    ui = Path(os.environ.get("HANDOVER_UI", "ui"))
    if ui.is_dir():
        app.mount("/", StaticFiles(directory=ui, html=True), name="ui")
    return app
