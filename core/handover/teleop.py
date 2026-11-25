import asyncio
import logging
import time
from dataclasses import dataclass, field

from .adapters import Unsupported
from .bus import Bus
from .fleet import Fleet
from .model import STOP, Event, Twist

log = logging.getLogger(__name__)

MAX_LINEAR = 0.5  # m/s, whatever the operator's keyboard says
MAX_ANGULAR = 0.8  # rad/s
DEADMAN = 0.25  # s without a packet before the robot is stopped
TICK = 0.02


class Busy(Exception):
    pass


def clamp(v: float, limit: float) -> float:
    return max(-limit, min(limit, v))


@dataclass
class Session:
    robot: str
    operator: str
    started: float = field(default_factory=time.monotonic)
    last: float = field(default_factory=time.monotonic)
    stopped: bool = True
    connected: bool = True


class Teleop:
    """Remote driving with a dead-man's switch.

    The browser sends a packet every 100 ms while the operator holds control,
    even when no key is down. If 250 ms pass without one (tab crashed, wifi
    dropped, laptop lid closed) the robot gets a zero velocity, once, and stays
    stopped until packets come back. Speed is capped here, not in the UI,
    because the UI is the part most likely to be wrong.
    """

    def __init__(self, bus: Bus, fleet: Fleet):
        self.bus, self.fleet = bus, fleet
        self.sessions: dict[str, Session] = {}
        self._watch: asyncio.Task | None = None

    def driving(self, robot: str) -> bool:
        return robot in self.sessions

    async def take(self, robot: str, operator: str) -> Session:
        adapter = self.fleet[robot]
        if not adapter.can_drive:
            raise Unsupported(f"{robot} speaks {adapter.protocol}, which has no velocity command")
        s = self.sessions.get(robot)
        if s and s.connected and s.operator != operator:
            raise Busy(f"{robot} is being driven by {s.operator}")
        await adapter.pause()
        await adapter.drive(STOP)
        s = self.sessions[robot] = Session(robot, operator)
        self.bus.publish(Event("takeover", robot, {"operator": operator}))
        if not self._watch or self._watch.done():
            self._watch = asyncio.create_task(self._deadman())
        return s

    async def command(self, robot: str, linear: float, angular: float) -> Twist:
        s = self.sessions[robot]
        s.last = time.monotonic()
        s.connected = True
        twist = Twist(clamp(linear, MAX_LINEAR), clamp(angular, MAX_ANGULAR))
        await self.fleet[robot].drive(twist)
        s.stopped = twist == STOP
        return twist

    def lost(self, robot: str) -> None:
        if s := self.sessions.get(robot):
            s.connected = False
            self.bus.publish(Event("operator_lost", robot, {"operator": s.operator}))

    async def release(self, robot: str) -> None:
        s = self.sessions.pop(robot, None)
        if not s:
            return
        adapter = self.fleet[robot]
        await adapter.drive(STOP)
        await adapter.resume()
        self.bus.publish(Event("released", robot, {
            "operator": s.operator, "held_for": round(time.monotonic() - s.started, 1),
        }))

    async def _deadman(self) -> None:
        while self.sessions:
            now = time.monotonic()
            for s in list(self.sessions.values()):
                if s.stopped or now - s.last < DEADMAN:
                    continue
                s.stopped = True
                try:
                    await self.fleet[s.robot].drive(STOP)
                except (ConnectionError, OSError) as e:
                    log.error("dead-man stop for %s did not go out: %s", s.robot, e)
                self.bus.publish(Event("deadman_stop", s.robot, {"silent_for": round(now - s.last, 3)}))
            await asyncio.sleep(TICK)
