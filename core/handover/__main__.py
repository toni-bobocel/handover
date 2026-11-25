import argparse
import getpass
import logging
import sys
from pathlib import Path

from . import fleet


def serve(a: argparse.Namespace) -> None:
    import uvicorn

    from .app import create

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # one worker on purpose: the ring buffers and teleop sessions live in this process
    uvicorn.run(create(a.config), host=a.host, port=a.port, log_level="warning", ws_ping_interval=5)


def users(a: argparse.Namespace) -> int:
    from .auth import Users

    u = Users(fleet.load(a.config).data / "users.toml")
    if a.action == "list":
        for x in u.all():
            print(f"{x.name:24} {x.role.name}")
        return 0
    if a.action == "remove":
        return 0 if u.remove(a.name) else 1
    password = getpass.getpass(f"password for {a.name}: ")
    if len(password) < 10:
        print("ten characters at least: this account can move machines", file=sys.stderr)
        return 1
    if getpass.getpass("again: ") != password:
        print("they do not match", file=sys.stderr)
        return 1
    u.add(a.name, a.role, password)
    print(f"{a.name} is a {a.role}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="handover")
    p.add_argument("--config", type=Path, default=Path("fleet.toml"))
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="run the console (the default)")

    us = sub.add_parser("users", help="manage operator accounts")
    us.add_argument("action", choices=["add", "remove", "list"])
    us.add_argument("name", nargs="?")
    us.add_argument("--role", default="viewer", choices=["viewer", "operator", "driver", "admin"])

    a = p.parse_args()
    if a.cmd == "users":
        if a.action != "list" and not a.name:
            p.error("which user?")
        sys.exit(users(a))
    serve(a)


if __name__ == "__main__":
    main()
