import random

from fleet_server.mock_robot import MockRobot


def goal(x, y, kind="task", goal_id="G-1"):
    return {"type": "navigate", "goal_id": goal_id, "kind": kind, "label": "s", "x": x, "y": y, "yaw": 0}


def run_until_result(robot, dt=0.1, limit=1000):
    for _ in range(limit):
        if result := robot.step(dt):
            return result
    raise AssertionError("goal never finished")


def test_drives_to_goal_and_drains_battery():
    robot = MockRobot("r", 0, 0, speed=1.0, drain_per_meter=1.0)
    robot.handle(goal(3, 4))
    result = run_until_result(robot)
    assert result == {"type": "goal_result", "goal_id": "G-1", "success": True, "reason": None}
    assert (round(robot.x, 3), round(robot.y, 3)) == (3, 4)
    assert round(robot.battery, 1) == 95.0  # 5 m driven


def test_charges_only_after_docking_at_charger():
    robot = MockRobot("r", 0, 0, speed=1.0, battery=50)
    robot.handle(goal(1, 0, kind="charge"))
    run_until_result(robot)
    before = robot.battery
    robot.step(5.0)
    assert robot.docked and robot.battery > before


def test_fail_rate_one_always_fails_midway():
    robot = MockRobot("r", 0, 0, speed=1.0, fail_rate=1.0, rng=random.Random(0))
    robot.handle(goal(10, 0))
    result = run_until_result(robot)
    assert result["success"] is False
    assert 4.5 <= robot.x <= 5.5


def test_cancel_stops_robot():
    robot = MockRobot("r", 0, 0, speed=1.0)
    robot.handle(goal(10, 0))
    robot.step(1.0)
    robot.handle({"type": "cancel"})
    x = robot.x
    assert robot.step(1.0) is None and robot.x == x
