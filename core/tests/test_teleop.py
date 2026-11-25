import asyncio

import pytest

from handover.adapters import Unsupported
from handover.model import STOP, Twist
from handover.teleop import DEADMAN, Busy, Teleop


async def test_speed_is_capped_whatever_the_browser_sends(bus, fleet):
    tele = Teleop(bus, fleet)
    await tele.take("r1", "ana")
    twist = await tele.command("r1", 4.0, -9.0)
    assert twist == Twist(0.5, -0.8)
    await tele.release("r1")


async def test_silence_stops_the_robot_once(bus, fleet):
    tele = Teleop(bus, fleet)
    await tele.take("r1", "ana")
    await tele.command("r1", 0.3, 0.0)
    before = fleet["r1"].stops
    await asyncio.sleep(DEADMAN + 0.15)
    assert fleet["r1"].stops == before + 1
    await asyncio.sleep(0.2)
    # still silent, but already stopped: no flood of zero commands
    assert fleet["r1"].stops == before + 1
    await tele.release("r1")


async def test_heartbeats_keep_it_moving(bus, fleet):
    tele = Teleop(bus, fleet)
    await tele.take("r1", "ana")
    for _ in range(6):
        await tele.command("r1", 0.3, 0.0)
        await asyncio.sleep(0.1)
    assert fleet["r1"].sent[-1] == Twist(0.3, 0.0)
    await tele.release("r1")


async def test_release_stops_then_hands_back(bus, fleet):
    tele = Teleop(bus, fleet)
    await tele.take("r1", "ana")
    await tele.command("r1", 0.2, 0.1)
    await tele.release("r1")
    assert fleet["r1"].sent[-2:] == [STOP, "resume"]
    assert not tele.driving("r1")


async def test_one_operator_at_a_time(bus, fleet):
    tele = Teleop(bus, fleet)
    await tele.take("r1", "ana")
    with pytest.raises(Busy):
        await tele.take("r1", "ben")
    tele.lost("r1")
    # ana's tab is gone: ben can take over
    await tele.take("r1", "ben")
    await tele.release("r1")


async def test_robots_without_velocity_control_refuse(bus, fleet):
    fleet["r1"].can_drive = False
    with pytest.raises(Unsupported):
        await Teleop(bus, fleet).take("r1", "ana")
