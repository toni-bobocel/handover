from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum


class Status(StrEnum):
    OK = "ok"
    NEEDS_ASSISTANCE = "needs_assistance"
    ESTOP = "estop"
    PAUSED = "paused"
    TELEOP = "teleop"
    OFFLINE = "offline"


@dataclass(slots=True)
class Telemetry:
    """One sample from one robot, already in site coordinates (metres, radians)."""

    robot: str
    x: float
    y: float
    heading: float
    speed: float = 0.0
    battery: float = 1.0
    status: Status = Status.OK
    blocked: bool = False
    estop: bool = False
    note: str = ""
    t: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Event:
    """Anything that is not telemetry: a rule firing, an operator action, a zone breach."""

    kind: str
    robot: str
    detail: dict = field(default_factory=dict)
    t: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class Twist:
    linear: float = 0.0
    angular: float = 0.0


STOP = Twist()
