"""Simulated robots that speak the fleet protocol, for demos and tests without ROS.

    python -m fleet_server.mock_robot --count 4 --fail-rate 0.05

Each robot drives in a straight line to its goal (no obstacle avoidance --
that's Nav2's job in the real stack), drains battery per metre, charges when
docked at a charger, and reconnects with backoff if the server goes away.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import math
import random

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

log = logging.getLogger("mock_robot")


class MockRobot:
    def __init__(
        self,
        robot_id: str,
        x: float,
        y: float,
        server: str = "ws://localhost:8000",
        speed: float = 0.6,
        drain_per_meter: float = 1.0,
        fail_rate: float = 0.0,
        rate_hz: float = 5.0,
        battery: float = 100.0,
        rng: random.Random | None = None,
    ):
        self.id = robot_id
        self.x, self.y, self.yaw = x, y, 0.0
        self.url = f"{server.rstrip('/')}/ws/robot/{robot_id}"
        self.speed = speed
        self.drain_per_meter = drain_per_meter
        self.fail_rate = fail_rate
        self.period = 1.0 / rate_hz
        self.battery = battery
        self.rng = rng or random.Random()
        self.goal: dict | None = None
        self.goal_fail_at: float | None = None  # remaining distance at which this goal "fails"
        self.docked = False

    # --------------------------------------------------------------- physics

    def step(self, dt: float) -> dict | None:
        """Advance the simulation by dt seconds. Returns a goal_result message when a goal ends."""
        if self.docked:
            self.battery = min(100.0, self.battery + 4.0 * dt)
            return None
        if self.goal is None:
            self.battery = max(0.0, self.battery - 0.01 * dt)  # idle electronics drain
            return None

        dx, dy = self.goal["x"] - self.x, self.goal["y"] - self.y
        remaining = math.hypot(dx, dy)
        if self.goal_fail_at is not None and remaining <= self.goal_fail_at:
            return self._finish(False, "simulated navigation failure (path blocked)")

        travel = min(remaining, self.speed * dt)
        if remaining > 1e-6:
            self.yaw = math.atan2(dy, dx)
            self.x += dx / remaining * travel
            self.y += dy / remaining * travel
        self.battery = max(0.0, self.battery - travel * self.drain_per_meter)

        if self.battery <= 0.0:
            return self._finish(False, "battery depleted")
        if remaining - travel <= 1e-3:
            self.docked = self.goal["kind"] == "charge"
            return self._finish(True, None)
        return None

    def _finish(self, success: bool, reason: str | None) -> dict:
        result = {"type": "goal_result", "goal_id": self.goal["goal_id"], "success": success, "reason": reason}
        self.goal = self.goal_fail_at = None
        return result

    def handle(self, msg: dict) -> None:
        if msg.get("type") == "navigate":
            self.goal = msg
            self.docked = False
            distance = math.hypot(msg["x"] - self.x, msg["y"] - self.y)
            self.goal_fail_at = distance / 2 if self.rng.random() < self.fail_rate else None
        elif msg.get("type") == "cancel":
            self.goal = self.goal_fail_at = None

    def telemetry(self) -> dict:
        return {
            "type": "telemetry",
            "pose": {"x": round(self.x, 3), "y": round(self.y, 3), "yaw": round(self.yaw, 3)},
            "battery": round(self.battery, 2),
        }

    # ------------------------------------------------------------ networking

    async def run(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with connect(self.url) as ws:
                    log.info("%s connected", self.id)
                    backoff = 1.0
                    await self._session(ws)
            except (OSError, WebSocketException) as e:
                log.warning("%s connection lost (%s); retrying in %.0fs", self.id, e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10.0)

    async def _session(self, ws: ClientConnection) -> None:
        async def receive() -> None:
            async for raw in ws:
                self.handle(json.loads(raw))

        receiver = asyncio.create_task(receive())
        try:
            loop = asyncio.get_running_loop()
            last = loop.time()
            while not receiver.done():
                now = loop.time()
                result = self.step(now - last)
                last = now
                if result:
                    await ws.send(json.dumps(result))
                await ws.send(json.dumps(self.telemetry()))
                await asyncio.sleep(self.period)
            receiver.result()  # re-raise whatever ended the receive loop
        finally:
            receiver.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await receiver


async def run_fleet(args: argparse.Namespace) -> None:
    rng = random.Random(args.seed)
    robots = [
        MockRobot(
            f"amr_{i + 1}",
            x=2.5,
            y=1.0 + 1.6 * i,
            server=args.server,
            speed=args.speed,
            fail_rate=args.fail_rate,
            battery=rng.uniform(45, 100),
            rng=random.Random(rng.random()),
        )
        for i in range(args.count)
    ]
    await asyncio.gather(*(r.run() for r in robots))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run simulated robots against a fleet server")
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--server", default="ws://localhost:8000")
    parser.add_argument("--speed", type=float, default=0.6, help="m/s")
    parser.add_argument("--fail-rate", type=float, default=0.05, help="chance a goal fails midway")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_fleet(args))


if __name__ == "__main__":
    main()
