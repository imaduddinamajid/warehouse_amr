"""Run the fleet server: python -m fleet_server [--config warehouse.yaml]"""

from __future__ import annotations

import argparse
import logging

import uvicorn

from .api import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Warehouse robot fleet server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--config", help="warehouse layout YAML (default: bundled demo map)")
    parser.add_argument("--tick-hz", type=float, default=5.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(args.config, tick_hz=args.tick_hz), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
