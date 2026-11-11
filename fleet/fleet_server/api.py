"""HTTP + WebSocket API around FleetManager.

All fleet mutations happen on the asyncio event loop (request handlers and
the control loop), so FleetManager needs no locks.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ValidationError

from .config import WarehouseConfig, load_config
from .fleet import FleetManager
from .models import Pose
from .protocol import GoalResultMsg, RobotMessage, TelemetryMsg

log = logging.getLogger("fleet_server")


class TaskRequest(BaseModel):
    pickup: str
    dropoff: str
    priority: int = 0


def create_app(
    config: WarehouseConfig | str | Path | None = None,
    tick_hz: float = 5.0,
    heartbeat_timeout: float = 5.0,
) -> FastAPI:
    cfg = config if isinstance(config, WarehouseConfig) else load_config(config)
    fleet = FleetManager(cfg, heartbeat_timeout=heartbeat_timeout)
    robot_sockets: dict[str, WebSocket] = {}
    dashboards: set[WebSocket] = set()

    async def send(ws: WebSocket, msg: dict) -> bool:
        try:
            await ws.send_json(msg)
            return True
        except Exception:  # socket closed mid-send; the receive loop will clean up
            return False

    async def control_loop() -> None:
        period = 1.0 / tick_hz
        while True:
            try:
                for robot_id, msg in fleet.tick():
                    if ws := robot_sockets.get(robot_id):
                        await send(ws, msg)
                snapshot = {"type": "state", **fleet.snapshot()}
                for ws in list(dashboards):
                    if not await send(ws, snapshot):
                        dashboards.discard(ws)
            except Exception:
                log.exception("control loop iteration failed")
            await asyncio.sleep(period)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        loop_task = asyncio.create_task(control_loop())
        yield
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task

    app = FastAPI(title="Warehouse Fleet Server", lifespan=lifespan)
    app.state.fleet = fleet

    # ------------------------------------------------------------------- REST

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "robots_connected": len(robot_sockets)}

    @app.get("/api/map")
    def get_map() -> dict:
        return cfg.to_dict()

    @app.get("/api/state")
    def get_state() -> dict:
        return fleet.snapshot()

    @app.post("/api/tasks", status_code=201)
    def submit_task(req: TaskRequest) -> dict:
        try:
            return fleet.submit_task(req.pickup, req.dropoff, req.priority).to_dict()
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/tasks/{task_id}/cancel")
    def cancel_task(task_id: str) -> dict:
        try:
            return fleet.cancel_task(task_id).to_dict()
        except KeyError as e:
            raise HTTPException(404, f"no task {task_id}") from e
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return resources.files("fleet_server").joinpath("static/index.html").read_text()

    # -------------------------------------------------------------- WebSockets

    @app.websocket("/ws/robot/{robot_id}")
    async def robot_socket(ws: WebSocket, robot_id: str) -> None:
        await ws.accept()
        if old := robot_sockets.get(robot_id):
            # Same robot id connected twice: the newest connection wins.
            with contextlib.suppress(Exception):
                await old.close(code=4000, reason="replaced by newer connection")
        robot_sockets[robot_id] = ws
        fleet.robot_connected(robot_id)
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = RobotMessage.validate_json(raw)
                except ValidationError as e:
                    await send(ws, {"type": "error", "detail": json.loads(e.json(include_url=False))})
                    continue
                if isinstance(msg, TelemetryMsg):
                    fleet.telemetry(robot_id, Pose(msg.pose.x, msg.pose.y, msg.pose.yaw), msg.battery)
                elif isinstance(msg, GoalResultMsg):
                    fleet.goal_result(robot_id, msg.goal_id, msg.success, msg.reason)
        except WebSocketDisconnect:
            pass
        finally:
            if robot_sockets.get(robot_id) is ws:
                del robot_sockets[robot_id]
                fleet.robot_disconnected(robot_id)

    @app.websocket("/ws/dashboard")
    async def dashboard_socket(ws: WebSocket) -> None:
        await ws.accept()
        dashboards.add(ws)
        try:
            while True:
                await ws.receive_text()  # dashboards only listen; this detects disconnects
        except WebSocketDisconnect:
            pass
        finally:
            dashboards.discard(ws)

    return app
