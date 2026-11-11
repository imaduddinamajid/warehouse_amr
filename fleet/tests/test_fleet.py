import pytest

from fleet_server.fleet import FleetManager
from fleet_server.models import Pose, RobotStatus, TaskStatus


@pytest.fixture
def fleet(cfg, clock):
    return FleetManager(cfg, clock=clock, heartbeat_timeout=5.0, max_attempts=2)


def join(fleet, robot_id, x=0.0, battery=100.0):
    fleet.robot_connected(robot_id)
    fleet.telemetry(robot_id, Pose(x, 0), battery)


def navigates(commands, robot_id):
    return [m for r, m in commands if r == robot_id and m["type"] == "navigate"]


def test_task_happy_path(fleet):
    join(fleet, "r1")
    task = fleet.submit_task("a", "b")

    [goal] = navigates(fleet.tick(), "r1")
    assert (goal["label"], goal["kind"]) == ("a", "task")
    assert task.status == TaskStatus.ACTIVE and fleet.robots["r1"].status == RobotStatus.BUSY

    fleet.goal_result("r1", goal["goal_id"], success=True)
    [goal2] = navigates(fleet.tick(), "r1")
    assert goal2["label"] == "b"

    fleet.goal_result("r1", goal2["goal_id"], success=True)
    assert task.status == TaskStatus.COMPLETED
    assert fleet.robots["r1"].status == RobotStatus.IDLE


def test_unknown_station_and_same_station_rejected(fleet):
    with pytest.raises(ValueError):
        fleet.submit_task("a", "nowhere")
    with pytest.raises(ValueError):
        fleet.submit_task("a", "a")


def test_failed_goal_requeues_then_fails_permanently(fleet):
    join(fleet, "r1")
    task = fleet.submit_task("a", "b")

    [goal] = navigates(fleet.tick(), "r1")
    fleet.goal_result("r1", goal["goal_id"], success=False, reason="blocked")
    assert task.status == TaskStatus.QUEUED and task.attempts == 1

    [goal] = navigates(fleet.tick(), "r1")
    fleet.goal_result("r1", goal["goal_id"], success=False, reason="blocked")
    assert task.status == TaskStatus.FAILED and task.error == "blocked"
    assert navigates(fleet.tick(), "r1") == []


def test_stale_goal_result_is_ignored(fleet):
    join(fleet, "r1")
    task = fleet.submit_task("a", "b")
    fleet.tick()
    fleet.goal_result("r1", "G-999", success=True)
    assert task.step == 0 and task.status == TaskStatus.ACTIVE


def test_heartbeat_timeout_requeues_task_to_another_robot(fleet, clock):
    join(fleet, "r1", x=4)
    join(fleet, "r2", x=0)
    task = fleet.submit_task("a", "b")
    fleet.tick()
    assert task.robot_id == "r1"

    clock.advance(3)
    fleet.telemetry("r2", Pose(0, 0), 100)  # r2 keeps reporting, r1 goes silent
    clock.advance(3)
    commands = fleet.tick()

    assert fleet.robots["r1"].status == RobotStatus.OFFLINE
    assert task.robot_id == "r2" and task.status == TaskStatus.ACTIVE
    assert task.attempts == 1  # losing a robot doesn't count against the task
    assert navigates(commands, "r2")[0]["label"] == "a"


def test_offline_robot_ignores_telemetry_until_reconnect(fleet):
    join(fleet, "r1")
    fleet.robot_disconnected("r1")
    fleet.telemetry("r1", Pose(3, 0), 50)
    assert fleet.robots["r1"].status == RobotStatus.OFFLINE

    fleet.robot_connected("r1")
    assert fleet.robots["r1"].status == RobotStatus.IDLE
    assert ("r1", {"type": "cancel"}) in fleet.tick()


def test_low_battery_robot_goes_to_nearest_free_charger_and_returns(fleet):
    join(fleet, "r1", x=5, battery=20)
    join(fleet, "r2", x=5, battery=20)
    commands = fleet.tick()

    goals = {r: m["label"] for r, m in commands if m["type"] == "navigate"}
    assert sorted(goals.values()) == ["ch1", "ch2"]  # no two robots share a charger
    r1 = fleet.robots["r1"]
    assert r1.status == RobotStatus.CHARGING

    goal_id = navigates(commands, "r1")[0]["goal_id"]
    fleet.goal_result("r1", goal_id, success=True)
    fleet.telemetry("r1", Pose(0, 0), 60)
    fleet.tick()
    assert r1.status == RobotStatus.CHARGING  # not charged enough yet

    fleet.telemetry("r1", Pose(0, 0), 95)
    fleet.tick()
    assert r1.status == RobotStatus.IDLE and r1.charger is None


def test_all_chargers_taken_robot_waits(fleet):
    for i in range(3):
        join(fleet, f"r{i}", x=5, battery=20)
    fleet.tick()
    statuses = sorted(r.status.value for r in fleet.robots.values())
    assert statuses == ["charging", "charging", "idle"]


def test_cancel_active_task_stops_robot(fleet):
    join(fleet, "r1")
    task = fleet.submit_task("a", "b")
    fleet.tick()
    fleet.cancel_task(task.id)

    assert task.status == TaskStatus.CANCELED
    assert fleet.robots["r1"].status == RobotStatus.IDLE
    assert ("r1", {"type": "cancel"}) in fleet.tick()
    with pytest.raises(ValueError):
        fleet.cancel_task(task.id)
