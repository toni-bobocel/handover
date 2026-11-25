import json
import time
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from handover.blackbox import Recorder
from handover.blackbox.bundle import verify
from handover.model import Event, Telemetry
from handover.rules import Limits, Watcher
from handover.store import Store


def kinds(q):
    out = []
    while not q.empty():
        m = q.get_nowait()
        if isinstance(m, Event):
            out.append(m.kind)
    return out


async def test_window_around_the_trigger_is_sealed(bus, tmp_path):
    key = Ed25519PrivateKey.generate()
    store = Store(tmp_path / "db.sqlite")
    rec = Recorder(bus, store, key, tmp_path / "inc", before=2, after=0.2)
    now = time.time()
    for i in range(60):
        rec.take(Telemetry("r1", i * 0.1, 0, 0, t=now - 5 + i * 0.1))
    rec.take(Event("estop", "r1", t=now))
    # a second trigger while the first is open joins it instead of opening another
    rec.take(Event("takeover", "r1", {"operator": "ana"}, t=now + 0.05))
    path = await rec.seal(rec.open["r1"])

    assert verify(path, key.public_key()) == []
    [row] = store.incidents()
    assert row["kind"] == "estop" and row["head"]
    with zipfile.ZipFile(path) as z:
        lines = [json.loads(x) for x in z.read("telemetry.jsonl").splitlines()]
        incident = json.loads(z.read("incident.json"))
    assert all(now - 2 <= r["t"] <= now + 0.2 for r in lines)
    assert incident["also"] == ["takeover"]


async def test_rules_fire_on_edges_only(bus):
    w = Watcher(bus, {}, Limits(blocked_after=2))
    async with bus.subscribe() as q:
        for t in range(5):
            w.check(Telemetry("r1", 0, 0, 0, battery=0.08, blocked=True, t=float(t)))
        w.check(Telemetry("r1", 0, 0, 0, battery=0.08, blocked=False, t=5.0))
        assert kinds(q) == ["battery_low", "needs_assistance", "assistance_cleared"]
