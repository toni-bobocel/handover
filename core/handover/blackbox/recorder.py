import asyncio
import logging
import time
from collections import defaultdict
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ..bus import Bus
from ..model import Event, Telemetry
from ..store import Store
from . import bundle
from .ring import Ring

log = logging.getLogger(__name__)

# what opens an incident; everything else is only kept in the ring
TRIGGERS = {"estop", "battery_low", "link_lost", "needs_assistance", "takeover", "zone_stop", "deadman_stop"}


class Recorder:
    def __init__(self, bus: Bus, store: Store, key: Ed25519PrivateKey, out: Path,
                 site: str = "", before: float = 30, after: float = 30):
        self.bus, self.store, self.key, self.out, self.site = bus, store, key, out, site
        self.before, self.after = before, after
        # a little longer than the window, so the oldest second is still there when we seal
        self.rings: dict[str, Ring] = defaultdict(lambda: Ring(before + after + 5))
        self.open: dict[str, dict] = {}
        self._tasks: set[asyncio.Task] = set()

    async def run(self) -> None:
        async with self.bus.subscribe() as q:
            while True:
                self.take(await q.get())

    def take(self, msg: Telemetry | Event) -> None:
        if isinstance(msg, Telemetry):
            self.rings[msg.robot].push(msg.t, {"type": "telemetry", **msg.as_dict()})
            return
        self.rings[msg.robot].push(msg.t, {"type": "event", **msg.as_dict()})
        if msg.kind not in TRIGGERS:
            return
        if msg.robot in self.open:
            # a takeover during a blocked-robot incident is part of the same story
            self.open[msg.robot]["also"].append(msg.kind)
            return
        incident = {
            "id": f"{time.strftime('%Y%m%d-%H%M%S', time.gmtime(msg.t))}-{msg.robot}",
            "robot": msg.robot, "kind": msg.kind, "t": msg.t, "site": self.site,
            "before": self.before, "after": self.after, "detail": msg.detail, "also": [],
        }
        self.open[msg.robot] = incident
        self.store.open_incident(incident["id"], msg.robot, msg.kind, msg.t)
        self.bus.publish(Event("incident_opened", msg.robot, {"id": incident["id"], "kind": msg.kind}))
        task = asyncio.create_task(self._seal_later(incident))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _seal_later(self, incident: dict) -> None:
        await asyncio.sleep(max(0.0, incident["t"] + self.after - time.time()))
        await self.seal(incident)

    async def seal(self, incident: dict) -> Path:
        robot, t0 = incident["robot"], incident["t"]
        records = self.rings[robot].window(t0 - self.before, t0 + self.after)
        path = self.out / f"{incident['id']}.rbox"
        head = await asyncio.to_thread(bundle.write, path, incident, records, self.key)
        size = path.stat().st_size
        self.store.seal_incident(incident["id"], path.name, head, size)
        self.open.pop(robot, None)
        log.info("sealed %s (%d records, %d bytes)", path.name, len(records), size)
        self.bus.publish(Event("incident_sealed", robot, {"id": incident["id"], "head": head, "bytes": size}))
        return path
