"""Three robots from three vendors, each speaking its own protocol to the core:

    AMR-Logistics-01      VDA 5050 over MQTT, through the site broker
    Humanoid-Inspect-02   a rosbridge server on :9090, as a ROS 2 robot would expose
    Cleaner-Bot-03        REST: posts its state to the core, takes commands on :7070
"""

import argparse
import asyncio
import json
import logging
import math
import os
import time
import tomllib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiomqtt
import httpx
import uvicorn
import websockets
from fastapi import FastAPI, HTTPException

from .world import Bot

log = logging.getLogger("sim")
HZ = 20


def stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def resume(b: Bot) -> None:
    # in the demo, resuming means someone checked the aisle: whatever blocked it is gone
    b.paused = False
    b.blocked_at = None
    b.note = ""
    b.cmd = None
    b.rejoin()


async def physics(bots: dict[str, Bot]) -> None:
    last = time.monotonic()
    while True:
        await asyncio.sleep(1 / HZ)
        now = time.monotonic()
        for b in bots.values():
            b.step(now - last)
        last = now


async def vda5050(b: Bot, cfg: dict) -> None:
    base = f"uagv/v2/{cfg['manufacturer']}/{cfg['serial']}"
    header = 0

    def state() -> dict:
        nonlocal header
        header += 1
        return {
            "headerId": header, "timestamp": stamp(), "version": "2.1.0",
            "manufacturer": cfg["manufacturer"], "serialNumber": cfg["serial"],
            "orderId": "loop", "orderUpdateId": 0, "lastNodeId": str(b.leg), "lastNodeSequenceId": b.leg,
            "driving": b.v > 0.01, "paused": b.paused, "operatingMode": "AUTOMATIC",
            "agvPosition": {"x": b.x, "y": b.y, "theta": b.heading, "mapId": "demo", "positionInitialized": True},
            "velocity": {"vx": b.v, "vy": 0.0, "omega": 0.0},
            "batteryState": {"batteryCharge": round(b.battery * 100, 1), "charging": False},
            "errors": [{"errorType": "noRouteError", "errorLevel": "WARNING"}] if b.blocked else [],
            "safetyState": {"eStop": "MANUAL" if b.estop else "NONE", "fieldViolation": b.blocked},
            "nodeStates": [], "edgeStates": [], "actionStates": [], "loads": [], "information": [],
        }

    async def listen(client: aiomqtt.Client) -> None:
        async for msg in client.messages:
            for a in json.loads(msg.payload).get("actions", []):
                if a["actionType"] == "startPause":
                    b.paused = True
                elif a["actionType"] == "stopPause":
                    resume(b)

    while True:
        try:
            async with aiomqtt.Client(cfg.get("broker", "localhost"), int(cfg.get("port", 1883)),
                                      identifier=f"sim-{cfg['serial']}") as client:
                await client.subscribe(f"{base}/instantActions", qos=1)
                listener = asyncio.create_task(listen(client))
                n = 0
                try:
                    while True:
                        await asyncio.sleep(0.1)
                        if b.silent:
                            continue
                        s = state()
                        # state at 1 Hz as the spec suggests, position on visualization at 10 Hz
                        if n % 10 == 0:
                            await client.publish(f"{base}/state", json.dumps(s))
                        await client.publish(f"{base}/visualization", json.dumps({
                            k: s[k] for k in ("headerId", "timestamp", "version", "manufacturer", "serialNumber",
                                              "agvPosition", "velocity")
                        }))
                        n += 1
                finally:
                    listener.cancel()
        except aiomqtt.MqttError as e:
            log.warning("broker unreachable (%s), retrying", e)
            await asyncio.sleep(2)


async def rosbridge(b: Bot, port: int) -> None:
    async def session(ws) -> None:
        subs: set[str] = set()

        async def pump() -> None:
            n = 0
            while True:
                await asyncio.sleep(0.1)
                n += 1
                if b.silent:
                    continue
                q = {"x": 0.0, "y": 0.0, "z": math.sin(b.heading / 2), "w": math.cos(b.heading / 2)}
                out = []
                if "/odom" in subs:
                    out.append(("/odom", {
                        "header": {"frame_id": "odom"},
                        "pose": {"pose": {"position": {"x": b.x, "y": b.y, "z": 0.0}, "orientation": q}},
                        "twist": {"twist": {"linear": {"x": b.v, "y": 0.0, "z": 0.0},
                                            "angular": {"x": 0.0, "y": 0.0, "z": 0.0}}},
                    }))
                if "/battery_state" in subs and n % 10 == 0:
                    out.append(("/battery_state", {"percentage": round(b.battery, 3), "power_supply_status": 2}))
                if "/diagnostics" in subs and n % 3 == 0:
                    out.append(("/diagnostics", {"status": [
                        {"level": 2 if b.estop else 0, "name": "safety/estop",
                         "message": "estop pressed" if b.estop else "ok"},
                        {"level": 1 if b.blocked else 0, "name": "nav/planner", "message": b.note or "ok"},
                    ]}))
                for topic, msg in out:
                    await ws.send(json.dumps({"op": "publish", "topic": topic, "msg": msg}))

        task = asyncio.create_task(pump())
        try:
            async for raw in ws:
                m = json.loads(raw)
                if m["op"] == "subscribe":
                    subs.add(m["topic"])
                elif m["op"] == "publish" and m["topic"].endswith("/cmd_vel"):
                    t = m["msg"]
                    b.cmd = (t["linear"]["x"], t["angular"]["z"])
                    b.cmd_t = time.time()
                elif m["op"] == "publish" and m["topic"].endswith("/handover/pause"):
                    if m["msg"]["data"]:
                        b.paused = True
                    else:
                        resume(b)
        finally:
            task.cancel()

    async with websockets.serve(session, "0.0.0.0", port):
        await asyncio.Event().wait()


async def rest_reporter(b: Bot, core: str) -> None:
    async with httpx.AsyncClient(timeout=1) as http:
        while True:
            await asyncio.sleep(0.2)
            if b.silent:
                continue
            try:
                await http.post(f"{core}/ingest/{b.id}", json={
                    "x": b.x, "y": b.y, "heading": b.heading, "speed": b.v, "battery": b.battery,
                    "blocked": b.blocked, "estop": b.estop, "note": b.note,
                })
            except httpx.HTTPError:
                pass  # the core is restarting; the next post will do


def control(bots: dict[str, Bot]) -> FastAPI:
    app = FastAPI(title="handover simulator")

    @app.post("/incident")
    def incident(body: dict):
        b = bots.get(body.get("robot", ""))
        if not b:
            raise HTTPException(404, "unknown robot")
        try:
            b.fail(body.get("kind", ""))
        except ValueError:
            raise HTTPException(422, "kind is one of obstacle, battery, estop, link") from None
        return {"ok": True, "id": uuid.uuid4().hex[:8]}

    @app.post("/robots/{id}/commands")
    def command(id: str, body: dict):
        b = bots[id]
        match body["cmd"]:
            case "pause":
                b.paused = True
            case "resume":
                resume(b)
            case "drive":
                b.cmd = (float(body["linear"]), float(body["angular"]))
                b.cmd_t = time.time()
        return {"ok": True}

    @app.get("/robots")
    def robots():
        return [{"id": b.id, "x": b.x, "y": b.y, "v": b.v, "blocked": b.blocked} for b in bots.values()]

    return app


async def main() -> None:
    p = argparse.ArgumentParser(prog="handover-sim")
    p.add_argument("--config", type=Path, default=Path("fleet.toml"))
    p.add_argument("--core", default=os.environ.get("HANDOVER_CORE", "http://localhost:8080"))
    p.add_argument("--port", type=int, default=7070)
    p.add_argument("--ros-port", type=int, default=9090)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s sim %(message)s")
    cfg = tomllib.loads(a.config.read_text(encoding="utf-8"))
    bots: dict[str, Bot] = {}
    jobs = [physics(bots)]
    for r in cfg["robot"]:
        b = bots[r["id"]] = Bot(r["id"], [tuple(p) for p in r["sim_route"]], r.get("sim_speed", 1.0))
        match r["protocol"]:
            case "vda5050":
                jobs.append(vda5050(b, r))
            case "ros2":
                jobs.append(rosbridge(b, a.ros_port))
            case "rest":
                jobs.append(rest_reporter(b, a.core))
    server = uvicorn.Server(uvicorn.Config(control(bots), host="0.0.0.0", port=a.port, log_level="warning"))
    jobs.append(server.serve())
    log.info("%d robots on the floor", len(bots))
    await asyncio.gather(*jobs)


if __name__ == "__main__":
    asyncio.run(main())
