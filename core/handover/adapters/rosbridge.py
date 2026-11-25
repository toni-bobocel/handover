import asyncio
import json
import logging
import math

import websockets

from ..model import Status, Telemetry, Twist
from .base import Adapter

log = logging.getLogger(__name__)

# diagnostic_msgs/DiagnosticStatus levels
WARN, ERROR = 1, 2


class Rosbridge(Adapter):
    """ROS 2 through rosbridge_server's JSON protocol. Nothing ROS has to be
    installed next to the core: the robot already runs rosbridge, or a five-line
    launch file adds it."""

    protocol = "ros2"
    can_drive = True

    def __init__(self, robot, cfg, bus):
        super().__init__(robot, cfg, bus)
        self.ns = cfg.get("namespace", "").rstrip("/")
        self._ws = None
        self._battery = 1.0
        self._blocked = False
        self._estop = False
        self._note = ""
        self._paused = False

    def _t(self, name: str) -> str:
        return f"{self.ns}/{name}"

    async def run(self) -> None:
        url = self.cfg["url"]
        subs = [
            ("odom", "nav_msgs/msg/Odometry", 100),
            ("battery_state", "sensor_msgs/msg/BatteryState", 1000),
            ("diagnostics", "diagnostic_msgs/msg/DiagnosticArray", 250),
        ]
        while True:
            try:
                async with websockets.connect(url, open_timeout=3) as ws:
                    self._ws = ws
                    for topic, kind, ms in subs:
                        await ws.send(json.dumps(
                            {"op": "subscribe", "topic": self._t(topic), "type": kind, "throttle_rate": ms}
                        ))
                    await ws.send(json.dumps(
                        {"op": "advertise", "topic": self._t("cmd_vel"), "type": "geometry_msgs/msg/Twist"}
                    ))
                    async for raw in ws:
                        m = json.loads(raw)
                        if m.get("op") == "publish":
                            self._on(m["topic"].rsplit("/", 1)[-1], m["msg"])
            except (OSError, websockets.WebSocketException) as e:
                self._ws = None
                log.warning("%s: rosbridge %s unreachable (%s), retrying", self.robot, url, e)
                await asyncio.sleep(2)

    def _on(self, topic: str, msg: dict) -> None:
        if topic == "battery_state":
            self._battery = msg["percentage"]
        elif topic == "diagnostics":
            worst = max(msg["status"], key=lambda s: s["level"], default=None)
            self._blocked = any(s["level"] >= WARN and "blocked" in s["message"] for s in msg["status"])
            self._estop = any(s["level"] >= ERROR and "estop" in s["name"] for s in msg["status"])
            self._note = worst["message"] if worst and worst["level"] else ""
        elif topic == "odom":
            p = msg["pose"]["pose"]
            q = p["orientation"]
            yaw = math.atan2(2 * (q["w"] * q["z"] + q["x"] * q["y"]), 1 - 2 * (q["y"] ** 2 + q["z"] ** 2))
            v = msg["twist"]["twist"]["linear"]
            status = Status.ESTOP if self._estop else Status.PAUSED if self._paused else Status.OK
            self.emit(Telemetry(
                robot=self.robot, x=p["position"]["x"], y=p["position"]["y"], heading=yaw,
                speed=math.hypot(v["x"], v["y"]), battery=self._battery,
                status=status, blocked=self._blocked, estop=self._estop, note=self._note,
            ))

    async def _publish(self, topic: str, msg: dict) -> None:
        if not self._ws:
            raise ConnectionError(f"{self.robot}: rosbridge not connected")
        await self._ws.send(json.dumps({"op": "publish", "topic": self._t(topic), "msg": msg}))

    async def drive(self, twist: Twist) -> None:
        await self._publish("cmd_vel", {
            "linear": {"x": twist.linear, "y": 0.0, "z": 0.0},
            "angular": {"x": 0.0, "y": 0.0, "z": twist.angular},
        })

    async def pause(self) -> None:
        self._paused = True
        await self._publish("handover/pause", {"data": True})

    async def resume(self) -> None:
        self._paused = False
        await self._publish("handover/pause", {"data": False})
