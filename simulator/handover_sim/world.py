"""A deliberately small world: robots follow a loop of waypoints at a set
speed, and the demo can make one of them fail in the ways real ones do."""

import math
import time
from dataclasses import dataclass, field


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


@dataclass
class Bot:
    id: str
    route: list[tuple[float, float]]
    speed: float
    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0
    v: float = 0.0
    battery: float = 0.92
    leg: int = 1
    paused: bool = False
    blocked_at: tuple[float, float] | None = None
    estop_until: float = 0.0
    silent_until: float = 0.0
    # teleop: the last velocity command and when it arrived
    cmd: tuple[float, float] | None = None
    cmd_t: float = 0.0
    note: str = ""
    errors: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.x, self.y = self.route[0]
        nx, ny = self.route[1]
        self.heading = math.atan2(ny - self.y, nx - self.x)

    @property
    def estop(self) -> bool:
        return time.time() < self.estop_until

    @property
    def blocked(self) -> bool:
        return self.blocked_at is not None

    @property
    def silent(self) -> bool:
        return time.time() < self.silent_until

    def step(self, dt: float) -> None:
        self.battery = max(0.0, self.battery - dt * 0.00004)
        driven = self.cmd is not None and time.time() - self.cmd_t < 0.5
        if self.estop:
            self.v = 0.0
            return
        if driven:
            lin, ang = self.cmd
            self.heading = wrap(self.heading + ang * dt)
            self.v = lin
            self.x += math.cos(self.heading) * lin * dt
            self.y += math.sin(self.heading) * lin * dt
            # a pallet does not move: once the robot is far enough round it, it is clear
            if self.blocked_at and math.dist((self.x, self.y), self.blocked_at) > 1.6:
                self.blocked_at = None
                self.note = ""
            return
        if self.paused or self.blocked:
            self.v = 0.0
            return
        tx, ty = self.route[self.leg]
        want = math.atan2(ty - self.y, tx - self.x)
        turn = wrap(want - self.heading)
        self.heading = wrap(self.heading + max(-2.5 * dt, min(2.5 * dt, turn)))
        # slow down for corners rather than spinning on the spot at full speed
        self.v = self.speed * max(0.15, math.cos(turn))
        d = math.hypot(tx - self.x, ty - self.y)
        stepd = min(d, self.v * dt)
        self.x += math.cos(self.heading) * stepd
        self.y += math.sin(self.heading) * stepd
        if d < 0.15:
            self.leg = (self.leg + 1) % len(self.route)

    def rejoin(self) -> None:
        """After a human drove it somewhere, head for the nearest waypoint."""
        self.leg = min(range(len(self.route)), key=lambda i: math.dist(self.route[i], (self.x, self.y)))

    def fail(self, kind: str) -> None:
        now = time.time()
        if kind == "obstacle":
            self.blocked_at = (self.x, self.y)
            self.note = "path blocked: pallet in the aisle"
        elif kind == "battery":
            self.battery = 0.08
        elif kind == "estop":
            self.estop_until = now + 8
        elif kind == "link":
            self.silent_until = now + 6
        else:
            raise ValueError(kind)
