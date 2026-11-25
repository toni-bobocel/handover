import math

from handover.adapters.rosbridge import Rosbridge
from handover.adapters.vda5050 import Vda5050
from handover.model import Status

VDA = {"manufacturer": "northwind", "serial": "amr-01"}


def test_vda5050_state_then_visualization(bus):
    a = Vda5050("amr", VDA, bus)
    assert a.base == "uagv/v2/northwind/amr-01"
    a._on("state", {
        "agvPosition": {"x": 3.0, "y": 4.0, "theta": 0.5},
        "velocity": {"vx": 0.6, "vy": 0.8},
        "batteryState": {"batteryCharge": 42.0},
        "safetyState": {"eStop": "NONE", "fieldViolation": True},
        "errors": [{"errorType": "noRouteError"}],
        "paused": False,
    })
    assert a.last.battery == 0.42 and a.last.blocked and a.last.speed == 1.0
    assert a.last.note == "noRouteError"
    # visualization carries only position: the rest comes from the last state
    a._on("visualization", {"agvPosition": {"x": 3.5, "y": 4.0, "theta": 0.5}, "velocity": {"vx": 0.2}})
    assert a.last.x == 3.5 and a.last.blocked and a.last.battery == 0.42


def test_vda5050_estop_wins_over_pause(bus):
    a = Vda5050("amr", VDA, bus)
    a._on("state", {"agvPosition": {"x": 0, "y": 0, "theta": 0}, "paused": True,
                    "safetyState": {"eStop": "MANUAL", "fieldViolation": False}})
    assert a.last.status == Status.ESTOP and a.last.estop


def test_rosbridge_quaternion_and_diagnostics(bus):
    a = Rosbridge("hum", {"url": "ws://x"}, bus)
    a._on("battery_state", {"percentage": 0.31})
    a._on("diagnostics", {"status": [
        {"level": 0, "name": "safety/estop", "message": "ok"},
        {"level": 1, "name": "nav/planner", "message": "path blocked: pallet"},
    ]})
    yaw = 2.0
    a._on("odom", {
        "pose": {"pose": {"position": {"x": 1.0, "y": 2.0},
                          "orientation": {"x": 0, "y": 0, "z": math.sin(yaw / 2), "w": math.cos(yaw / 2)}}},
        "twist": {"twist": {"linear": {"x": 0.3, "y": 0.4}}},
    })
    t = a.last
    assert math.isclose(t.heading, yaw) and math.isclose(t.speed, 0.5)
    assert t.blocked and not t.estop and t.battery == 0.31 and t.note == "path blocked: pallet"
