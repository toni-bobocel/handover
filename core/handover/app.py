import asyncio
import contextlib
import hmac
import json
import logging
import os
import time
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import fleet as fleet_mod
from .adapters import Unsupported
from .adapters.rest import Rest
from .auth import Role, Sessions, Throttle, User, Users
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
    users = Users(cfg.data / "users.toml")
    sessions = Sessions(cfg.data / "session.key")
    throttle = Throttle()
    # the demo has no accounts: everyone who opens it is an admin called "demo"
    open_site = bool(cfg.auth.get("open"))
    COOKIE = "handover_session"

    def who(cookies) -> User | None:
        if open_site:
            return User("demo", Role.admin)
        name = sessions.read(cookies.get(COOKIE))
        return users.get(name) if name else None

    def need(role: Role):
        def check(request: Request) -> User:
            u = who(request.cookies)
            if not u:
                raise HTTPException(401, "log in first")
            if u.role < role:
                raise HTTPException(403, f"needs the {role.name} role")
            return u
        return check

    viewer, operator, driver, admin = (Depends(need(r)) for r in Role)

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

    @app.post("/api/login")
    def login(body: dict, request: Request, response: Response):
        ip = request.client.host if request.client else "?"
        if throttle.blocked(ip):
            raise HTTPException(429, "too many attempts, wait a minute")
        u = users.login(str(body.get("name", "")), str(body.get("password", "")))
        if not u:
            throttle.miss(ip)
            raise HTTPException(401, "wrong name or password")
        response.set_cookie(COOKIE, sessions.issue(u.name), httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", max_age=12 * 3600)
        bus.publish(Event("login", "*", {"user": u.name}))
        return {"name": u.name, "role": u.role.name}

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE)

    @app.get("/api/me")
    def me(request: Request):
        u = who(request.cookies)
        if not u:
            raise HTTPException(401, "log in first")
        return {"name": u.name, "role": u.role.name, "open": open_site, "accounts": open_site or bool(users.all())}

    @app.get("/api/site", dependencies=[viewer])
    def site():
        return {"name": cfg.site, "plan": cfg.plan, "robots": fleet.describe(), "zones": list(guard.zones.values()),
                "demo": bool(cfg.sim_url)}

    @app.get("/api/incidents", dependencies=[viewer])
    def incidents():
        return store.incidents()

    @app.get("/api/incidents/{id}/bundle", dependencies=[operator])
    def download(id: str):
        inc = store.incident(id)
        if not inc or not inc["bundle"]:
            raise HTTPException(404, "not sealed yet")
        return FileResponse(cfg.data / "incidents" / inc["bundle"], media_type="application/zip",
                            filename=inc["bundle"])

    @app.get("/api/site.pub", dependencies=[viewer])
    def public_key():
        return FileResponse(cfg.data / "site.pub", media_type="application/x-pem-file", filename="site.pub")

    @app.post("/api/robots/{id}/pause")
    async def pause(id: str, u: User = operator):
        await robot(id).pause()
        bus.publish(Event("paused", id, {"by": u.name}))

    @app.post("/api/robots/{id}/resume")
    async def resume(id: str, u: User = operator):
        await robot(id).resume()
        bus.publish(Event("resumed", id, {"by": u.name}))

    @app.post("/ingest/{id}")
    async def ingest(id: str, request: Request):
        a = robot(id)
        if not isinstance(a, Rest):
            raise HTTPException(409, f"{id} does not report over REST")
        # robots are not users: each REST robot can be given its own token in fleet.toml
        token = a.cfg.get("token")
        given = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token and not hmac.compare_digest(given, token):
            raise HTTPException(401, "bad robot token")
        a.ingest(await request.json())
        return {"ok": True}

    @app.put("/api/zones/{id}", dependencies=[admin])
    async def put_zone(id: str, body: dict):
        z = Zone.parse({**body, "id": id})
        if len(z.polygon) < 3:
            raise HTTPException(422, "a zone needs at least three corners")
        store.put_zone({**body, "id": id})
        guard.zones[id] = z
        bus.publish(Event("zone_changed", "*", {"id": id}))
        return z

    @app.delete("/api/zones/{id}", dependencies=[admin])
    async def delete_zone(id: str):
        store.delete_zone(id)
        guard.zones.pop(id, None)
        bus.publish(Event("zone_changed", "*", {"id": id}))

    @app.post("/api/demo/{id}/{kind}", dependencies=[operator])
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
        if not who(ws.cookies):
            await ws.close(code=4401, reason="log in first")
            return
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
        u = who(ws.cookies)
        if not u or u.role < Role.driver:
            await ws.close(code=4403, reason="needs the driver role")
            return
        try:
            robot(id)
            await teleop.take(id, u.name)
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

    ui = Path(os.environ.get("HANDOVER_UI", "ui/dist"))
    if ui.is_dir():
        app.mount("/", StaticFiles(directory=ui, html=True), name="ui")
    return app
