from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

from .models import Pose


@dataclass
class WarehouseConfig:
    name: str
    size: tuple[float, float]
    stations: dict[str, Pose]
    chargers: dict[str, Pose]
    obstacles: list[list[float]] = field(default_factory=list)
    drain_per_meter: float = 1.0
    reserve: float = 10.0
    low_battery: float = 25.0
    charged_battery: float = 90.0

    def to_dict(self) -> dict:
        def poses(d: dict[str, Pose]) -> dict:
            return {k: {"x": p.x, "y": p.y} for k, p in d.items()}

        return {
            "name": self.name,
            "size": list(self.size),
            "stations": poses(self.stations),
            "chargers": poses(self.chargers),
            "obstacles": self.obstacles,
        }


def _poses(raw: dict) -> dict[str, Pose]:
    return {name: Pose(float(p["x"]), float(p["y"]), float(p.get("yaw", 0.0))) for name, p in raw.items()}


def load_config(path: str | Path | None = None) -> WarehouseConfig:
    """Load a warehouse layout. Falls back to $FLEET_CONFIG, then the bundled demo map."""
    path = path or os.environ.get("FLEET_CONFIG")
    if path:
        text = Path(path).read_text()
    else:
        text = resources.files("fleet_server").joinpath("config/warehouse.yaml").read_text()
    raw = yaml.safe_load(text)

    battery = raw.get("battery", {})
    cfg = WarehouseConfig(
        name=raw.get("name", "warehouse"),
        size=tuple(raw["size"]),
        stations=_poses(raw["stations"]),
        chargers=_poses(raw.get("chargers", {})),
        obstacles=raw.get("obstacles", []),
        drain_per_meter=float(battery.get("drain_per_meter", 1.0)),
        reserve=float(battery.get("reserve", 10.0)),
        low_battery=float(battery.get("low", 25.0)),
        charged_battery=float(battery.get("charged", 90.0)),
    )
    if not cfg.chargers:
        raise ValueError("warehouse config needs at least one charger")
    return cfg
