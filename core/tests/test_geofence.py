import math
from datetime import datetime

import pytest

from handover.geofence import Guard, Zone, distance, inside
from handover.model import Telemetry

SQUARE = [(0, 0), (4, 0), (4, 4), (0, 4)]


def test_distance_to_a_square():
    assert inside((2, 2), SQUARE)
    assert distance((2, 2), SQUARE) == 0
    assert distance((6, 2), SQUARE) == pytest.approx(2)
    assert distance((5, 5), SQUARE) == pytest.approx(math.sqrt(2))


def test_schedule_across_midnight():
    z = Zone("z", "night dock", SQUARE, start="22:00", end="06:00")
    assert z.active(datetime(2026, 1, 1, 23, 30))
    assert z.active(datetime(2026, 1, 1, 5, 59))
    assert not z.active(datetime(2026, 1, 1, 12, 0))


def at(x, y, heading=0.0, speed=0.0, t=0.0):
    return Telemetry("r1", x, y, heading, speed=speed, t=t)


async def test_pauses_a_robot_heading_in(bus, fleet):
    g = Guard(bus, fleet, [Zone("dock", "Truck dock", SQUARE)])
    await g.check(at(5.5, 2, heading=math.pi, speed=1.2))
    assert fleet["r1"].sent == ["pause"]
    # stopped where it is: no second pause
    await g.check(at(5.4, 2, heading=math.pi, speed=0.0, t=0.5))
    assert fleet["r1"].sent == ["pause"]


async def test_pauses_again_if_resumed_towards_the_zone(bus, fleet):
    g = Guard(bus, fleet, [Zone("dock", "Truck dock", SQUARE)])
    await g.check(at(4.8, 2, speed=0.0))
    await g.check(at(4.7, 2, heading=math.pi, speed=0.6, t=3.0))
    assert fleet["r1"].sent == ["pause", "pause"]


async def test_leaves_alone_robots_driving_past(bus, fleet):
    g = Guard(bus, fleet, [Zone("dock", "Truck dock", SQUARE)])
    await g.check(at(7, -3, heading=math.pi / 2, speed=1.0))
    assert fleet["r1"].sent == []


async def test_only_warns_when_a_human_is_driving(bus, fleet):
    g = Guard(bus, fleet, [Zone("dock", "Truck dock", SQUARE)], is_driven=lambda r: True)
    async with bus.subscribe() as q:
        await g.check(at(4.5, 2))
        assert q.get_nowait().kind == "zone_warning"
    assert fleet["r1"].sent == []
