import asyncio
import json
import logging
import shutil
import time
import zipfile
from collections import defaultdict
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ..bus import Bus
from ..model import Event, Telemetry
from ..store import Store
from . import bundle, video
from .ring import Ring

log = logging.getLogger(__name__)

# what opens an incident; everything else is only kept in the ring
TRIGGERS = {"estop", "battery_low", "link_lost", "needs_assistance", "takeover", "zone_stop", "deadman_stop"}


class Recorder:
    def __init__(self, bus: Bus, store: Store, key: Ed25519PrivateKey, out: Path,
                 site: str = "", before: float = 30, after: float = 30, export: Path | None = None,
                 cameras: dict[str, str] | None = None, recordings: Path | None = None):
        self.bus, self.store, self.key, self.out, self.site = bus, store, key, out, site
        self.export = export
        self.cameras = cameras or {}
        self.recordings = recordings
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
        for job in (self._first_draft(incident), self._seal_later(incident)):
            task = asyncio.create_task(job)
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _first_draft(self, incident: dict) -> None:
        # the half that already happened goes to disk now: if the process dies in
        # the next thirty seconds, the seconds before the trigger survive
        robot, t0 = incident["robot"], incident["t"]
        records = self.rings[robot].window(t0 - self.before, t0)
        draft = {**incident, "after": 0, "partial": True}
        clips = self._clips(robot, t0 - self.before, t0)
        await asyncio.to_thread(bundle.write, self._partial(incident["id"]), draft, records, self.key, clips)
        if self.open.get(robot) is not incident:
            # sealed while the draft was being written: the draft is no longer needed
            self._partial(incident["id"]).unlink(missing_ok=True)

    def _clips(self, robot: str, start: float, end: float) -> dict[str, bytes]:
        camera = self.cameras.get(robot)
        if not camera or not self.recordings:
            return {}
        return video.segments(self.recordings, camera, start, end)

    def _partial(self, id: str) -> Path:
        return self.out / f"{id}.partial.rbox"

    async def _seal_later(self, incident: dict) -> None:
        await asyncio.sleep(max(0.0, incident["t"] + self.after - time.time()))
        if self.open.get(incident["robot"]) is incident:
            await self.seal(incident)

    def recover(self) -> int:
        """On start: incidents the last run opened but never sealed keep their first draft."""
        n = 0
        for row in self.store.incidents(limit=1000):
            draft = self._partial(row["id"])
            if row["bundle"] or not draft.exists():
                continue
            with zipfile.ZipFile(draft) as z:
                head = json.loads(z.read("manifest.json"))["chain_head"]
            self.store.seal_incident(row["id"], draft.name, head, draft.stat().st_size)
            log.warning("%s was cut short by a restart; kept the %.0f s before it", row["id"], self.before)
            n += 1
        return n

    async def seal(self, incident: dict) -> Path:
        robot, t0 = incident["robot"], incident["t"]
        # closed before the first await, so a second caller sees it gone and leaves it alone
        self.open.pop(robot, None)
        records = self.rings[robot].window(t0 - self.before, t0 + self.after)
        clips = self._clips(robot, t0 - self.before, t0 + self.after)
        incident = {**incident, "video": sorted(clips)}
        path = self.out / f"{incident['id']}.rbox"
        head = await asyncio.to_thread(bundle.write, path, incident, records, self.key, clips)
        size = path.stat().st_size
        self.store.seal_incident(incident["id"], path.name, head, size)
        self._partial(incident["id"]).unlink(missing_ok=True)
        if self.export:
            await asyncio.to_thread(self._copy_out, path)
        log.info("sealed %s (%d records, %d bytes)", path.name, len(records), size)
        self.bus.publish(Event("incident_sealed", robot, {"id": incident["id"], "head": head, "bytes": size}))
        return path

    def _copy_out(self, path: Path) -> None:
        try:
            self.export.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, self.export / path.name)
        except OSError as e:
            # the NAS is down or full: the bundle is safe here, prune() tries again later
            log.error("could not export %s to %s: %s", path.name, self.export, e)

    def prune(self, keep_days: float, max_bytes: int) -> list[str]:
        """Removes sealed bundles older than keep_days, then the oldest until under max_bytes.
        Bundles not yet copied to the export folder are never removed."""
        gone = []
        rows = [r for r in self.store.incidents(limit=100_000) if r["bundle"] and not r["pruned"]]
        rows.sort(key=lambda r: r["t"])
        total = sum(r["bytes"] or 0 for r in rows)
        cutoff = time.time() - keep_days * 86400
        for r in rows:
            if r["t"] >= cutoff and total <= max_bytes:
                break
            path = self.out / r["bundle"]
            if self.export and not (self.export / r["bundle"]).exists():
                self._copy_out(path)
                if not (self.export / r["bundle"]).exists():
                    continue
            path.unlink(missing_ok=True)
            self.store.prune_incident(r["id"])
            total -= r["bytes"] or 0
            gone.append(r["id"])
        if gone:
            log.info("pruned %d bundles, %d bytes left", len(gone), total)
        return gone
