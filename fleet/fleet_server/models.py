"""Core domain types for the fleet manager.

These are plain dataclasses with no I/O so the scheduling logic can be
unit-tested without a network, ROS, or a simulator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class RobotStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    CHARGING = "charging"  # driving to, or docked at, a charger
    OFFLINE = "offline"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


TERMINAL_TASK_STATES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED}


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    yaw: float = 0.0

    def distance_to(self, other: Pose) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass
class Robot:
    id: str
    pose: Pose = Pose(0.0, 0.0)
    battery: float = 100.0
    status: RobotStatus = RobotStatus.IDLE
    task_id: str | None = None
    goal_id: str | None = None
    goal_kind: str | None = None  # "task" or "charge"
    goal_label: str | None = None
    charger: str | None = None
    last_seen: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "pose": {"x": self.pose.x, "y": self.pose.y, "yaw": self.pose.yaw},
            "battery": round(self.battery, 1),
            "status": self.status.value,
            "task_id": self.task_id,
            "goal_label": self.goal_label,
            "charger": self.charger,
        }


@dataclass
class Task:
    """Move something from a pickup station to a dropoff station."""

    id: str
    pickup: str
    dropoff: str
    created_at: float
    priority: int = 0
    status: TaskStatus = TaskStatus.QUEUED
    robot_id: str | None = None
    step: int = 0  # index into waypoints: 0 = heading to pickup, 1 = heading to dropoff
    attempts: int = 0
    finished_at: float | None = None
    error: str | None = None

    @property
    def waypoints(self) -> list[str]:
        return [self.pickup, self.dropoff]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "pickup": self.pickup,
            "dropoff": self.dropoff,
            "priority": self.priority,
            "status": self.status.value,
            "robot_id": self.robot_id,
            "step": self.step,
            "attempts": self.attempts,
            "error": self.error,
        }
