"""End-to-end through HTTP and WebSockets, using the same protocol a real robot speaks."""

import pytest
from fastapi.testclient import TestClient

from fleet_server.api import create_app


@pytest.fixture
def client(cfg):
    with TestClient(create_app(cfg, tick_hz=50)) as c:
        yield c


def next_of_type(ws, type_):
    for _ in range(50):
        msg = ws.receive_json()
        if msg["type"] == type_:
            return msg
    raise AssertionError(f"no {type_} message received")


def test_map_and_health(client):
    assert client.get("/healthz").json()["ok"] is True
    assert set(client.get("/api/map").json()["stations"]) == {"a", "b", "c"}


def test_submit_validation(client):
    assert client.post("/api/tasks", json={"pickup": "a", "dropoff": "zzz"}).status_code == 400
    assert client.post("/api/tasks/T-404/cancel").status_code == 404


def test_robot_completes_task_over_websocket(client):
    with client.websocket_connect("/ws/robot/r1") as ws:
        ws.send_json({"type": "telemetry", "pose": {"x": 0, "y": 0}, "battery": 100})
        task = client.post("/api/tasks", json={"pickup": "a", "dropoff": "b"}).json()
        assert task["status"] == "queued"

        for station in ("a", "b"):
            goal = next_of_type(ws, "navigate")
            assert goal["label"] == station
            ws.send_json({"type": "telemetry", "pose": {"x": goal["x"], "y": goal["y"]}, "battery": 90})
            ws.send_json({"type": "goal_result", "goal_id": goal["goal_id"], "success": True})

        # The control loop runs in the background, so poll briefly for the final state.
        for _ in range(100):
            [t] = client.get("/api/state").json()["tasks"]
            if t["status"] == "completed":
                break
            ws.send_json({"type": "telemetry", "pose": {"x": 10, "y": 0}, "battery": 90})
        assert t["status"] == "completed"


def test_malformed_robot_message_gets_error_not_disconnect(client):
    with client.websocket_connect("/ws/robot/r1") as ws:
        ws.send_text('{"type": "telemetry", "battery": 500}')
        assert next_of_type(ws, "error")["detail"]
        ws.send_json({"type": "telemetry", "pose": {"x": 1, "y": 2}, "battery": 50})
        for _ in range(100):
            [robot] = client.get("/api/state").json()["robots"]
            if robot["pose"]["x"] == 1:
                break
        assert robot["battery"] == 50


def test_disconnect_marks_robot_offline(client):
    with client.websocket_connect("/ws/robot/r1") as ws:
        ws.send_json({"type": "telemetry", "pose": {"x": 0, "y": 0}, "battery": 100})
    for _ in range(100):  # server-side cleanup runs asynchronously after the close
        [robot] = client.get("/api/state").json()["robots"]
        if robot["status"] == "offline":
            break
    assert robot["status"] == "offline"
