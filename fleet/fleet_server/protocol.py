"""Robot <-> fleet server wire protocol (JSON over WebSocket /ws/robot/{robot_id}).

Robot -> server:
    {"type": "telemetry", "pose": {"x": 1.0, "y": 2.0, "yaw": 0.0}, "battery": 87.5}
    {"type": "goal_result", "goal_id": "G-12", "success": true, "reason": null}

Server -> robot:
    {"type": "navigate", "goal_id": "G-12", "kind": "task" | "charge",
     "label": "shelf_a", "x": 5.0, "y": 5.6, "yaw": 0.0}
    {"type": "cancel"}

Robots must send telemetry at least every heartbeat_timeout seconds (default
5s) or they are marked offline and their task is requeued. Mock robots and
the ROS 2 agent both implement this same protocol.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class PoseMsg(BaseModel):
    x: float
    y: float
    yaw: float = 0.0


class TelemetryMsg(BaseModel):
    type: Literal["telemetry"]
    pose: PoseMsg
    battery: float = Field(ge=0, le=100)


class GoalResultMsg(BaseModel):
    type: Literal["goal_result"]
    goal_id: str
    success: bool
    reason: str | None = None


RobotMessage = TypeAdapter(Annotated[TelemetryMsg | GoalResultMsg, Field(discriminator="type")])
