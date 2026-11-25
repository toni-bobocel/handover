import argparse
import logging
from pathlib import Path

import uvicorn

from .app import create


def main() -> None:
    p = argparse.ArgumentParser(prog="handover")
    p.add_argument("--config", type=Path, default=Path("fleet.toml"))
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # one worker on purpose: the ring buffers and teleop sessions live in this process
    uvicorn.run(create(a.config), host=a.host, port=a.port, log_level="warning", ws_ping_interval=5)


if __name__ == "__main__":
    main()
