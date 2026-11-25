import time
from abc import ABC, abstractmethod

from ..bus import Bus
from ..model import Telemetry, Twist


class Unsupported(Exception):
    pass


class Adapter(ABC):
    """Everything the core knows about a robot goes through one of these.

    `run` owns the connection for the life of the process and reconnects on
    its own; the core never sees a vendor message, only Telemetry on the bus.
    """

    protocol: str
    can_drive = False

    def __init__(self, robot: str, cfg: dict, bus: Bus):
        self.robot = robot
        self.cfg = cfg
        self.bus = bus
        self.last: Telemetry | None = None

    def emit(self, t: Telemetry) -> None:
        self.last = t
        self.bus.publish(t)

    def silent_for(self, now: float | None = None) -> float:
        if self.last is None:
            return float("inf")
        return (now or time.time()) - self.last.t

    @abstractmethod
    async def run(self) -> None: ...

    @abstractmethod
    async def pause(self) -> None: ...

    @abstractmethod
    async def resume(self) -> None: ...

    async def drive(self, twist: Twist) -> None:
        # VDA 5050 has no velocity command, by design: an AMR is told where to
        # go, not how to steer. Those robots can be paused, not driven.
        raise Unsupported(f"{self.robot} ({self.protocol}) cannot be driven remotely")
