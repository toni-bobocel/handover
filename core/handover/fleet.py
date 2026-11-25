import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import PROTOCOLS, Adapter
from .bus import Bus


@dataclass
class Config:
    site: str
    data: Path
    robots: list[dict]
    rules: dict = field(default_factory=dict)
    zones: list[dict] = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    auth: dict = field(default_factory=dict)
    blackbox: dict = field(default_factory=dict)
    sim_url: str | None = None
    tls: bool = False
    tls_names: list[str] = field(default_factory=list)


def load(path: Path) -> Config:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    site = raw.get("site", {})
    return Config(
        site=site.get("name", "site"),
        data=Path(site.get("data", "data")),
        robots=raw.get("robot", []),
        rules=raw.get("rules", {}),
        zones=raw.get("zone", []),
        plan=raw.get("plan", {}),
        auth=raw.get("auth", {}),
        blackbox=raw.get("blackbox", {}),
        sim_url=site.get("simulator"),
        tls=bool(site.get("tls")),
        tls_names=site.get("tls_names", []),
    )


class Fleet(dict[str, Adapter]):
    def __init__(self, robots: list[dict], bus: Bus):
        super().__init__()
        for r in robots:
            cls = PROTOCOLS[r["protocol"]]
            self[r["id"]] = cls(r["id"], r, bus)
        self.meta = {r["id"]: {"label": r.get("label", r["id"]), "kind": r.get("kind", "")} for r in robots}

    def describe(self) -> list[dict]:
        return [
            {"id": id, "protocol": a.protocol, "can_drive": a.can_drive, **self.meta[id],
             "last": a.last.as_dict() if a.last else None}
            for id, a in self.items()
        ]
