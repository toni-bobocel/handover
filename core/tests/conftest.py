import pytest

from handover.adapters.base import Adapter
from handover.bus import Bus
from handover.model import STOP


class FakeRobot(Adapter):
    protocol = "fake"
    can_drive = True

    def __init__(self, robot="r1", bus=None):
        super().__init__(robot, {}, bus or Bus())
        self.sent: list = []

    async def run(self):
        pass

    async def pause(self):
        self.sent.append("pause")

    async def resume(self):
        self.sent.append("resume")

    async def drive(self, twist):
        self.sent.append(twist)

    @property
    def stops(self):
        return sum(1 for s in self.sent if s == STOP)


@pytest.fixture
def bus():
    return Bus()


@pytest.fixture
def fleet(bus):
    return {"r1": FakeRobot("r1", bus)}
