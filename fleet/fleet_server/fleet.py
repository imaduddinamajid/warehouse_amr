"""Fleet state machine.

FleetManager owns all robot and task state. It never does I/O: inputs are
method calls (telemetry, goal results, task requests) and outputs are
commands returned from tick(). The API layer feeds it from a single asyncio
event loop, so no locking is needed.
"""

from __future__ import annotations

import itertools
import time
from collections import deque
from collections.abc import Callable

from .allocator import allocate
from .config import WarehouseConfig
from .models import TERMINAL_TASK_STATES, Pose, Robot, RobotStatus, Task, TaskStatus

Command = tuple[str, dict]  # (robot_id, message)


class FleetManager:
    def __init__(
        self,
        cfg: WarehouseConfig,
        clock: Callable[[], float] = time.monotonic,
        heartbeat_timeout: float = 5.0,
        max_attempts: int = 3,
    ):
        self.cfg = cfg
        self.clock = clock
        self.heartbeat_timeout = heartbeat_timeout
        self.max_attempts = max_attempts
        self.robots: dict[str, Robot] = {}
        self.tasks: dict[str, Task] = {}
        self.events: deque[dict] = deque(maxlen=100)
        self._outbox: list[Command] = []
        self._task_seq = itertools.count(1)
        self._goal_seq = itertools.count(1)

    # ------------------------------------------------------------------ robots

    def robot_connected(self, robot_id: str) -> None:
        robot = self.robots.get(robot_id)
        if robot is None:
            robot = self.robots[robot_id] = Robot(id=robot_id)
            self._log(f"{robot_id} joined the fleet")
        else:
            # We don't know what the robot did while we couldn't see it, so
            # requeue any work it held and tell it to stop.
            self._release(robot, "reconnected")
            self._log(f"{robot_id} reconnected")
        robot.status = RobotStatus.IDLE
        robot.last_seen = self.clock()
        self._outbox.append((robot_id, {"type": "cancel"}))

    def robot_disconnected(self, robot_id: str) -> None:
        robot = self.robots.get(robot_id)
        if robot and robot.status != RobotStatus.OFFLINE:
            self._mark_offline(robot, "disconnected")

    def telemetry(self, robot_id: str, pose: Pose, battery: float) -> None:
        robot = self.robots.get(robot_id)
        if robot is None or robot.status == RobotStatus.OFFLINE:
            return
        robot.pose = pose
        robot.battery = max(0.0, min(100.0, battery))
        robot.last_seen = self.clock()

    def goal_result(self, robot_id: str, goal_id: str, success: bool, reason: str | None = None) -> None:
        robot = self.robots.get(robot_id)
        if robot is None or goal_id != robot.goal_id:
            return  # stale result for a goal we already canceled or reassigned
        kind = robot.goal_kind
        robot.goal_id = robot.goal_kind = robot.goal_label = None

        if kind == "charge":
            if not success:
                self._log(f"{robot_id} could not reach {robot.charger}: {reason}")
                robot.status, robot.charger = RobotStatus.IDLE, None
            return  # success: stays CHARGING until the battery is full enough

        task = self.tasks.get(robot.task_id) if robot.task_id else None
        if task is None or task.status != TaskStatus.ACTIVE:
            self._free(robot)
            return
        if not success:
            self._log(f"{task.id} failed on {robot_id}: {reason}")
            self._requeue_or_fail(task, reason or "navigation failed")
            self._free(robot)
            return

        task.step += 1
        if task.step >= len(task.waypoints):
            task.status, task.finished_at = TaskStatus.COMPLETED, self.clock()
            self._log(f"{task.id} completed by {robot_id}")
            self._free(robot)
        else:
            self._send_task_goal(robot, task)

    # ------------------------------------------------------------------- tasks

    def submit_task(self, pickup: str, dropoff: str, priority: int = 0) -> Task:
        for station in (pickup, dropoff):
            if station not in self.cfg.stations:
                raise ValueError(f"unknown station: {station}")
        if pickup == dropoff:
            raise ValueError("pickup and dropoff must differ")
        task = Task(
            id=f"T-{next(self._task_seq):04d}",
            pickup=pickup,
            dropoff=dropoff,
            priority=priority,
            created_at=self.clock(),
        )
        self.tasks[task.id] = task
        self._log(f"{task.id} queued: {pickup} -> {dropoff}")
        return task

    def cancel_task(self, task_id: str) -> Task:
        task = self.tasks[task_id]  # KeyError -> 404 at the API layer
        if task.status in TERMINAL_TASK_STATES:
            raise ValueError(f"{task_id} is already {task.status.value}")
        if task.robot_id and (robot := self.robots.get(task.robot_id)):
            self._outbox.append((robot.id, {"type": "cancel"}))
            self._free(robot)
        task.status, task.robot_id, task.finished_at = TaskStatus.CANCELED, None, self.clock()
        self._log(f"{task_id} canceled")
        return task

    # -------------------------------------------------------------- scheduling

    def tick(self) -> list[Command]:
        """Run one control cycle and return the commands to send to robots."""
        now = self.clock()
        for robot in self.robots.values():
            if robot.status != RobotStatus.OFFLINE and now - robot.last_seen > self.heartbeat_timeout:
                self._mark_offline(robot, "heartbeat timeout")

        for robot in self.robots.values():
            if (
                robot.status == RobotStatus.CHARGING
                and robot.goal_id is None
                and robot.battery >= self.cfg.charged_battery
            ):
                self._log(f"{robot.id} charged to {robot.battery:.0f}%, back to work")
                robot.status, robot.charger = RobotStatus.IDLE, None

        for robot in self.robots.values():
            if robot.status == RobotStatus.IDLE and robot.battery < self.cfg.low_battery:
                self._send_to_charger(robot)

        for task_id, robot_id in allocate(self.tasks.values(), self.robots.values(), self.cfg):
            task, robot = self.tasks[task_id], self.robots[robot_id]
            task.status, task.robot_id, task.step = TaskStatus.ACTIVE, robot_id, 0
            task.attempts += 1
            robot.status, robot.task_id = RobotStatus.BUSY, task_id
            self._log(f"{task_id} assigned to {robot_id}")
            self._send_task_goal(robot, task)

        out, self._outbox = self._outbox, []
        return out

    def snapshot(self) -> dict:
        tasks = sorted(self.tasks.values(), key=lambda t: t.created_at, reverse=True)
        counts = {s.value: 0 for s in TaskStatus}
        for t in self.tasks.values():
            counts[t.status.value] += 1
        return {
            "robots": [r.to_dict() for r in sorted(self.robots.values(), key=lambda r: r.id)],
            "tasks": [t.to_dict() for t in tasks[:50]],
            "task_counts": counts,
            "events": list(self.events)[-30:],
        }

    # ---------------------------------------------------------------- internal

    def _send_task_goal(self, robot: Robot, task: Task) -> None:
        station = task.waypoints[task.step]
        self._send_goal(robot, "task", station, self.cfg.stations[station])

    def _send_to_charger(self, robot: Robot) -> None:
        taken = {r.charger for r in self.robots.values() if r.charger}
        free = {name: pose for name, pose in self.cfg.chargers.items() if name not in taken}
        if not free:
            return  # wait for a charger to free up; we'll retry next tick
        name = min(free, key=lambda n: robot.pose.distance_to(free[n]))
        robot.status, robot.charger = RobotStatus.CHARGING, name
        self._log(f"{robot.id} low battery ({robot.battery:.0f}%), heading to {name}")
        self._send_goal(robot, "charge", name, free[name])

    def _send_goal(self, robot: Robot, kind: str, label: str, pose: Pose) -> None:
        goal_id = f"G-{next(self._goal_seq)}"
        robot.goal_id, robot.goal_kind, robot.goal_label = goal_id, kind, label
        self._outbox.append(
            (
                robot.id,
                {"type": "navigate", "goal_id": goal_id, "kind": kind, "label": label,
                 "x": pose.x, "y": pose.y, "yaw": pose.yaw},
            )
        )

    def _requeue_or_fail(self, task: Task, reason: str) -> None:
        task.robot_id, task.step = None, 0
        if task.attempts >= self.max_attempts:
            task.status, task.error, task.finished_at = TaskStatus.FAILED, reason, self.clock()
            self._log(f"{task.id} failed permanently after {task.attempts} attempts")
        else:
            task.status = TaskStatus.QUEUED

    def _release(self, robot: Robot, reason: str) -> None:
        """Drop whatever the robot was doing and put its task back in the queue."""
        if robot.task_id and (task := self.tasks.get(robot.task_id)) and task.status == TaskStatus.ACTIVE:
            # Losing a robot isn't the task's fault, so don't burn an attempt.
            task.attempts -= 1
            self._requeue_or_fail(task, reason)
            self._log(f"{task.id} requeued ({robot.id} {reason})")
        self._free(robot)
        robot.charger = None

    def _mark_offline(self, robot: Robot, reason: str) -> None:
        self._release(robot, reason)
        robot.status = RobotStatus.OFFLINE
        self._log(f"{robot.id} offline: {reason}")

    def _free(self, robot: Robot) -> None:
        robot.status = RobotStatus.IDLE
        robot.task_id = robot.goal_id = robot.goal_kind = robot.goal_label = None

    def _log(self, msg: str) -> None:
        self.events.append({"t": time.time(), "msg": msg})
