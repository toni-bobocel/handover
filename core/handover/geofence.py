import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, time

from .bus import Bus
from .fleet import Fleet
from .model import Event, Telemetry

log = logging.getLogger(__name__)

Point = tuple[float, float]


def inside(p: Point, poly: list[Point]) -> bool:
    x, y = p
    hit = False
    j = len(poly) - 1
    for i in range(len(poly)):
        (xi, yi), (xj, yj) = poly[i], poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def distance(p: Point, poly: list[Point]) -> float:
    """Metres from p to the zone's edge, 0 inside it."""
    if inside(p, poly):
        return 0.0
    best = math.inf
    for a, b in zip(poly, poly[1:] + poly[:1], strict=True):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = dx * dx + dy * dy
        u = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
        best = min(best, math.hypot(p[0] - a[0] - u * dx, p[1] - a[1] - u * dy))
    return best


@dataclass
class Zone:
    id: str
    name: str
    polygon: list[Point]
    margin: float = 1.0
    # "08:00"–"10:00" in site time; empty means always
    start: str = ""
    end: str = ""
    robots: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, d: dict) -> "Zone":
        return cls(**{**d, "polygon": [tuple(p) for p in d["polygon"]]})

    def active(self, now: datetime) -> bool:
        if not self.start:
            return True
        a, b, t = time.fromisoformat(self.start), time.fromisoformat(self.end), now.time()
        return a <= t < b if a <= b else t >= a or t < b

    def applies(self, robot: str) -> bool:
        return not self.robots or robot in self.robots


# look a little ahead: at 1.5 m/s a robot covers the 1 m margin in under a second
LOOKAHEAD = 0.6


class Guard:
    """Stops any robot, whatever its brand, before it enters a no-go zone.

    The robot is paused, not steered: it stays where it stopped until someone
    resumes it or drives it out by hand. Nothing here decides a path for a
    machine whose vendor stack knows its own kinematics better than we do.
    """

    def __init__(self, bus: Bus, fleet: Fleet, zones: list[Zone], is_driven=lambda robot: False):
        self.bus, self.fleet = bus, fleet
        self.zones = {z.id: z for z in zones}
        self.is_driven = is_driven
        # (robot, zone) -> when we last stopped it there
        self.held: dict[tuple[str, str], float] = {}

    def near(self, t: Telemetry, now: datetime | None = None) -> list[tuple[Zone, float]]:
        now = now or datetime.now()
        ahead = (t.x + math.cos(t.heading) * t.speed * LOOKAHEAD, t.y + math.sin(t.heading) * t.speed * LOOKAHEAD)
        out = []
        for z in self.zones.values():
            if not (z.active(now) and z.applies(t.robot)):
                continue
            d = min(distance((t.x, t.y), z.polygon), distance(ahead, z.polygon))
            if d < z.margin:
                out.append((z, d))
        return out

    async def check(self, t: Telemetry) -> None:
        close = self.near(t)
        for z, d in close:
            key = (t.robot, z.id)
            last = self.held.get(key)
            # stopped and still stopped: nothing to do. Moving again (someone pressed
            # resume without driving it out): stop it again.
            if last is not None and (t.speed < 0.05 or t.t - last < 1.0):
                continue
            self.held[key] = t.t
            if self.is_driven(t.robot):
                # a human has the wheel: warn, do not yank control from under them
                self.bus.publish(Event("zone_warning", t.robot, {"zone": z.id, "distance": round(d, 2)}))
                continue
            try:
                await self.fleet[t.robot].pause()
            except Exception as e:
                # the event below must go out whatever the adapter did
                log.error("could not pause %s at zone %s: %s", t.robot, z.id, e)
            self.bus.publish(Event("zone_stop", t.robot, {"zone": z.id, "name": z.name, "distance": round(d, 2)}))
        names = {z.id for z, _ in close}
        for k in [k for k in self.held if k[0] == t.robot and k[1] not in names]:
            del self.held[k]

    async def run(self) -> None:
        async with self.bus.subscribe() as q:
            while True:
                msg = await q.get()
                if isinstance(msg, Telemetry):
                    await self.check(msg)

