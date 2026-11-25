import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
create table if not exists incident (
  id text primary key,
  robot text not null,
  kind text not null,
  t real not null,
  bundle text,
  head text,
  bytes integer
);
create index if not exists incident_t on incident (t desc);
create table if not exists zone (
  id text primary key,
  body text not null
);
create table if not exists audit (
  t real not null,
  robot text not null,
  kind text not null,
  detail text not null
);
"""


class Store:
    """SQLite in WAL mode: the web UI reads while the recorder writes, and
    there is nothing for the site's IT to administer. Only incidents, zones and
    operator actions land here, a few rows a minute, so the loop calls it
    directly; telemetry never does."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma journal_mode=wal")
        self.db.execute("pragma synchronous=normal")
        self.db.executescript(SCHEMA)
        self._lock = threading.Lock()

    def _x(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self._lock:
            return self.db.execute(sql, args).fetchall()

    def open_incident(self, id: str, robot: str, kind: str, t: float) -> None:
        self._x("insert into incident (id, robot, kind, t) values (?, ?, ?, ?)", (id, robot, kind, t))

    def seal_incident(self, id: str, bundle: str, head: str, size: int) -> None:
        self._x("update incident set bundle = ?, head = ?, bytes = ? where id = ?", (bundle, head, size, id))

    def incidents(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self._x("select * from incident order by t desc limit ?", (limit,))]

    def incident(self, id: str) -> dict | None:
        rows = self._x("select * from incident where id = ?", (id,))
        return dict(rows[0]) if rows else None

    def audit(self, t: float, robot: str, kind: str, detail: dict) -> None:
        self._x("insert into audit values (?, ?, ?, ?)", (t, robot, kind, json.dumps(detail)))

    def zones(self) -> list[dict]:
        return [json.loads(r["body"]) for r in self._x("select body from zone order by id")]

    def put_zone(self, zone: dict) -> None:
        self._x("insert or replace into zone values (?, ?)", (zone["id"], json.dumps(zone)))

    def delete_zone(self, id: str) -> None:
        self._x("delete from zone where id = ?", (id,))
