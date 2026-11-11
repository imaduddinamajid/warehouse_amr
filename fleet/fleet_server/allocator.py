"""Task allocation: decide which idle robot takes which queued task.

Greedy by priority, then age: each task goes to the nearest idle robot that
has enough battery to finish it *and* still reach a charger afterwards.
Greedy is not optimal (see the Hungarian algorithm for that), but it is
predictable, O(tasks * robots), and easy to reason about when debugging a
live fleet.
"""

from __future__ import annotations

from collections.abc import Iterable

from .config import WarehouseConfig
from .models import Pose, Robot, RobotStatus, Task, TaskStatus


def nearest_charger_distance(pose: Pose, cfg: WarehouseConfig) -> float:
    return min(pose.distance_to(c) for c in cfg.chargers.values())


def battery_needed(robot: Robot, task: Task, cfg: WarehouseConfig) -> float:
    """Battery % needed to do `task` from where `robot` is now, then reach a charger."""
    pickup = cfg.stations[task.pickup]
    dropoff = cfg.stations[task.dropoff]
    distance = (
        robot.pose.distance_to(pickup)
        + pickup.distance_to(dropoff)
        + nearest_charger_distance(dropoff, cfg)
    )
    return distance * cfg.drain_per_meter + cfg.reserve


def allocate(
    tasks: Iterable[Task], robots: Iterable[Robot], cfg: WarehouseConfig
) -> list[tuple[str, str]]:
    """Return (task_id, robot_id) assignments for this scheduling round."""
    free = [r for r in robots if r.status == RobotStatus.IDLE]
    queued = sorted(
        (t for t in tasks if t.status == TaskStatus.QUEUED),
        key=lambda t: (-t.priority, t.created_at),
    )

    assignments: list[tuple[str, str]] = []
    for task in queued:
        if not free:
            break
        capable = [r for r in free if r.battery >= battery_needed(r, task, cfg)]
        if not capable:
            continue
        pickup = cfg.stations[task.pickup]
        best = min(capable, key=lambda r: (r.pose.distance_to(pickup), r.id))
        assignments.append((task.id, best.id))
        free.remove(best)
    return assignments
