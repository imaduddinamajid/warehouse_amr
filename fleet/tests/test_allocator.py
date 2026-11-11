from fleet_server.allocator import allocate, battery_needed
from fleet_server.models import Pose, Robot, RobotStatus, Task, TaskStatus


def task(id, pickup="a", dropoff="b", priority=0, created_at=0.0):
    return Task(id=id, pickup=pickup, dropoff=dropoff, priority=priority, created_at=created_at)


def test_battery_needed_includes_return_to_charger(cfg):
    robot = Robot("r1", pose=Pose(0, 0))
    # 0->a (5) + a->b (5) + b->nearest charger (10) = 20 m, plus 10% reserve
    assert battery_needed(robot, task("t"), cfg) == 30.0


def test_nearest_idle_robot_wins(cfg):
    far = Robot("far", pose=Pose(0, 0))
    near = Robot("near", pose=Pose(4, 0))
    assert allocate([task("t1")], [far, near], cfg) == [("t1", "near")]


def test_busy_offline_and_charging_robots_are_skipped(cfg):
    robots = [
        Robot("busy", pose=Pose(5, 0), status=RobotStatus.BUSY),
        Robot("off", pose=Pose(5, 0), status=RobotStatus.OFFLINE),
        Robot("chg", pose=Pose(5, 0), status=RobotStatus.CHARGING),
        Robot("free", pose=Pose(0, 0)),
    ]
    assert allocate([task("t1")], robots, cfg) == [("t1", "free")]


def test_priority_then_age_ordering(cfg):
    tasks = [
        task("old", created_at=1),
        task("urgent", priority=5, created_at=3),
        task("new", created_at=2),
    ]
    robot = Robot("r1", pose=Pose(0, 0))
    assert allocate(tasks, [robot], cfg) == [("urgent", "r1")]


def test_robot_without_enough_battery_is_not_assigned(cfg):
    weak = Robot("weak", pose=Pose(5, 0), battery=20)  # needs 0+5+10+10 = 25
    assert allocate([task("t1")], [weak], cfg) == []


def test_low_battery_robot_still_takes_a_shorter_task(cfg):
    weak = Robot("weak", pose=Pose(5, 0), battery=26)
    long_trip = task("long", pickup="a", dropoff="c", created_at=0)  # 0+10+15+10 = 35
    short_trip = task("short", pickup="a", dropoff="b", created_at=1)  # 0+5+10+10 = 25
    assert allocate([long_trip, short_trip], [weak], cfg) == [("short", "weak")]


def test_each_robot_gets_at_most_one_task(cfg):
    robots = [Robot("r1", pose=Pose(0, 0)), Robot("r2", pose=Pose(0, 0))]
    tasks = [task(f"t{i}", created_at=i) for i in range(5)]
    result = allocate(tasks, robots, cfg)
    assert [t for t, _ in result] == ["t0", "t1"]
    assert {r for _, r in result} == {"r1", "r2"}


def test_only_queued_tasks_are_considered(cfg):
    active = task("active")
    active.status = TaskStatus.ACTIVE
    assert allocate([active], [Robot("r1")], cfg) == []
