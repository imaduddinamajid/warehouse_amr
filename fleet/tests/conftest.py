import pytest

from fleet_server.config import WarehouseConfig
from fleet_server.models import Pose


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def cfg() -> WarehouseConfig:
    """A tiny 1-D warehouse: easy to compute distances in your head."""
    return WarehouseConfig(
        name="test",
        size=(20, 5),
        stations={"a": Pose(5, 0), "b": Pose(10, 0), "c": Pose(15, 0)},
        chargers={"ch1": Pose(0, 0), "ch2": Pose(0, 1)},
        drain_per_meter=1.0,
        reserve=10.0,
        low_battery=25.0,
        charged_battery=90.0,
    )
