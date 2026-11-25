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
    cfg = fleet.load(a.config)
    ssl = {}
    if cfg.tls:
        from .tls import ensure

        cert, key = ensure(cfg.data / "tls", cfg.tls_names)
        ssl = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
    # one worker on purpose: the ring buffers and teleop sessions live in this process
    uvicorn.run(create(a.config), host=a.host, port=a.port, log_level="warning", ws_ping_interval=5, **ssl)


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


def plan(a: argparse.Namespace) -> int:
    from . import dxf

    segs = dxf.read(a.drawing, scale=a.scale, layers=set(a.layer) if a.layer else None)
    if not segs:
        print("no LINE or LWPOLYLINE on those layers", file=sys.stderr)
        return 1
    info = dxf.save(segs, fleet.load(a.config).data / "plan-lines.json")
    print(f"{info['segments']} segments, {info['width']} x {info['height']} m. "
          f"Set [plan] width and height to at least that and restart.")
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

    pl = sub.add_parser("plan", help="import walls and racks from a DXF drawing")
    pl.add_argument("drawing", type=Path)
    pl.add_argument("--scale", type=float, default=0.001, help="metres per drawing unit (0.001 for millimetres)")
    pl.add_argument("--layer", action="append", help="only these layers; repeat for several")

    a = p.parse_args()
    if a.cmd == "plan":
        sys.exit(plan(a))
    if a.cmd == "users":
        if a.action != "list" and not a.name:
            p.error("which user?")
        sys.exit(users(a))
    serve(a)


if __name__ == "__main__":
    main()
