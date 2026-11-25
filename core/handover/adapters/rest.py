import asyncio

import httpx

from ..model import Status, Telemetry, Twist
from .base import Adapter


class Rest(Adapter):
    """For robots that only speak HTTP: they POST their state to
    /ingest/{robot} and expose one endpoint for commands. Common on cleaning
    and delivery robots whose vendor cloud is the only other option."""

    protocol = "rest"
    can_drive = True

    def __init__(self, robot, cfg, bus):
        super().__init__(robot, cfg, bus)
        self._http = httpx.AsyncClient(timeout=1.5)
        self._paused = False

    async def run(self) -> None:
        # inbound only: the HTTP route calls ingest()
        await asyncio.Event().wait()

    def ingest(self, body: dict) -> Telemetry:
        estop = bool(body.get("estop"))
        status = Status.ESTOP if estop else Status.PAUSED if self._paused else Status.OK
        t = Telemetry(
            robot=self.robot, x=float(body["x"]), y=float(body["y"]), heading=float(body.get("heading", 0)),
            speed=float(body.get("speed", 0)), battery=float(body.get("battery", 1)),
            status=status, blocked=bool(body.get("blocked")), estop=estop, note=str(body.get("note", "")),
        )
        self.emit(t)
        return t

    async def _send(self, body: dict) -> None:
        r = await self._http.post(self.cfg["command_url"], json=body)
        r.raise_for_status()

    async def drive(self, twist: Twist) -> None:
        await self._send({"cmd": "drive", "linear": twist.linear, "angular": twist.angular})

    async def pause(self) -> None:
        self._paused = True
        await self._send({"cmd": "pause"})

    async def resume(self) -> None:
        self._paused = False
        await self._send({"cmd": "resume"})
