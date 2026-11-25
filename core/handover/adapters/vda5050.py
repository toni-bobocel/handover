import asyncio
import itertools
import json
import logging
import uuid
from datetime import UTC, datetime

import aiomqtt

from ..model import Status, Telemetry
from .base import Adapter

log = logging.getLogger(__name__)


class Vda5050(Adapter):
    """VDA 5050 over MQTT. Reads `state` (1 Hz or on change, per the spec) and
    `visualization` (the high-rate position topic), sends `instantActions`."""

    protocol = "vda5050"

    def __init__(self, robot, cfg, bus):
        super().__init__(robot, cfg, bus)
        c = cfg
        self.base = f"{c.get('interface', 'uagv')}/{c.get('major', 'v2')}/{c['manufacturer']}/{c['serial']}"
        self._header = itertools.count(1)
        self._client: aiomqtt.Client | None = None
        self._state: dict = {}

    async def run(self) -> None:
        host = self.cfg.get("broker", "localhost")
        port = int(self.cfg.get("port", 1883))
        while True:
            try:
                async with aiomqtt.Client(host, port, identifier=f"handover-{self.robot}") as client:
                    self._client = client
                    await client.subscribe(f"{self.base}/state", qos=0)
                    await client.subscribe(f"{self.base}/visualization", qos=0)
                    async for msg in client.messages:
                        self._on(str(msg.topic).rsplit("/", 1)[-1], json.loads(msg.payload))
            except aiomqtt.MqttError as e:
                self._client = None
                log.warning("%s: broker %s:%s unreachable (%s), retrying", self.robot, host, port, e)
                await asyncio.sleep(2)

    def _on(self, topic: str, body: dict) -> None:
        if topic == "state":
            self._state = body
        pos = body.get("agvPosition")
        if not pos:
            return
        st = self._state
        safety = st.get("safetyState", {})
        estop = safety.get("eStop", "NONE") != "NONE"
        blocked = bool(safety.get("fieldViolation"))
        vel = body.get("velocity") or st.get("velocity") or {}
        status = Status.ESTOP if estop else Status.PAUSED if st.get("paused") else Status.OK
        self.emit(Telemetry(
            robot=self.robot,
            x=pos["x"], y=pos["y"], heading=pos["theta"],
            speed=(vel.get("vx", 0.0) ** 2 + vel.get("vy", 0.0) ** 2) ** 0.5,
            battery=st.get("batteryState", {}).get("batteryCharge", 100.0) / 100,
            status=status, blocked=blocked, estop=estop,
            note=", ".join(e.get("errorType", "") for e in st.get("errors", [])),
        ))

    async def _instant(self, action: str) -> None:
        if not self._client:
            raise ConnectionError(f"{self.robot}: not connected to the broker")
        msg = {
            "headerId": next(self._header),
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "version": "2.1.0",
            "manufacturer": self.cfg["manufacturer"],
            "serialNumber": self.cfg["serial"],
            "actions": [{"actionType": action, "actionId": uuid.uuid4().hex, "blockingType": "HARD"}],
        }
        await self._client.publish(f"{self.base}/instantActions", json.dumps(msg), qos=1)

    async def pause(self) -> None:
        await self._instant("startPause")

    async def resume(self) -> None:
        await self._instant("stopPause")

