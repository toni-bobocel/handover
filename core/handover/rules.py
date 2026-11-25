import asyncio
from dataclasses import dataclass

from .bus import Bus
from .fleet import Fleet
from .model import Event, Telemetry


@dataclass
class Limits:
    battery_low: float = 0.10
    link_lost_after: float = 3.0
    blocked_after: float = 15.0


class Watcher:
    """Turns telemetry into the handful of events an operator cares about.
    Edge-triggered: a robot sitting at 9 % battery raises one event, not ten
    a second."""

    def __init__(self, bus: Bus, fleet: Fleet, limits: Limits):
        self.bus, self.fleet, self.limits = bus, fleet, limits
        self.flags: dict[tuple[str, str], bool] = {}
        self.blocked_since: dict[str, float] = {}

    def _edge(self, robot: str, flag: str, on: bool, detail: dict | None = None,
              off_kind: str | None = None) -> None:
        was = self.flags.get((robot, flag), False)
        if on and not was:
            self.bus.publish(Event(flag, robot, detail or {}))
        elif was and not on and off_kind:
            self.bus.publish(Event(off_kind, robot, {}))
        self.flags[(robot, flag)] = on

    def assisting(self, robot: str) -> bool:
        return self.flags.get((robot, "needs_assistance"), False)

    def check(self, t: Telemetry) -> None:
        L = self.limits
        self._edge(t.robot, "estop", t.estop, off_kind="estop_cleared")
        self._edge(t.robot, "battery_low", t.battery < L.battery_low, {"battery": round(t.battery, 3)})
        if t.blocked:
            since = self.blocked_since.setdefault(t.robot, t.t)
            stuck = t.t - since >= L.blocked_after
            self._edge(t.robot, "needs_assistance", stuck,
                       {"blocked_for": round(t.t - since, 1), "note": t.note}, off_kind="assistance_cleared")
        else:
            self.blocked_since.pop(t.robot, None)
            self._edge(t.robot, "needs_assistance", False, off_kind="assistance_cleared")

    async def run(self) -> None:
        async with self.bus.subscribe() as q:
            ticker = asyncio.create_task(self._links())
            try:
                while True:
                    msg = await q.get()
                    if isinstance(msg, Telemetry):
                        self.check(msg)
            finally:
                ticker.cancel()

    async def _links(self) -> None:
        # silence is not a message, so it has to be polled for
        while True:
            for robot, a in self.fleet.items():
                if a.last is None:
                    continue
                gone = a.silent_for() > self.limits.link_lost_after
                self._edge(robot, "link_lost", gone, {"after": self.limits.link_lost_after},
                           off_kind="link_restored")
            await asyncio.sleep(0.5)
