import asyncio
import json
import os
import time
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from handover.blackbox import Recorder
from handover.blackbox.bundle import load_key, verify
from handover.model import Event, Telemetry
from handover.store import Store


def fill(rec: Recorder, now: float) -> None:
    for i in range(40):
        rec.take(Telemetry("r1", i * 0.1, 0, 0, t=now - 4 + i * 0.1))


async def test_a_crash_keeps_the_seconds_before(bus, tmp_path):
    key = Ed25519PrivateKey.generate()
    store = Store(tmp_path / "db.sqlite")
    rec = Recorder(bus, store, key, tmp_path / "inc", before=3, after=60)
    now = time.time()
    fill(rec, now)
    rec.take(Event("estop", "r1", t=now))
    await asyncio.sleep(0.2)
    for t in list(rec._tasks):
        t.cancel()  # the process dies here, long before the 60 s are up

    again = Recorder(bus, Store(tmp_path / "db.sqlite"), key, tmp_path / "inc", before=3, after=60)
    assert again.recover() == 1
    [row] = store.incidents()
    assert row["bundle"].endswith(".partial.rbox")
    path = tmp_path / "inc" / row["bundle"]
    assert verify(path, key.public_key()) == []
    with zipfile.ZipFile(path) as z:
        assert json.loads(z.read("incident.json"))["partial"] is True


async def test_old_bundles_go_once_they_are_exported(bus, tmp_path):
    key = Ed25519PrivateKey.generate()
    store = Store(tmp_path / "db.sqlite")
    nas = tmp_path / "nas"
    rec = Recorder(bus, store, key, tmp_path / "inc", before=1, after=0, export=nas)
    now = time.time()
    for robot in ("r1", "r2"):
        rec.take(Telemetry(robot, 0, 0, 0, t=now))
        rec.take(Event("estop", robot, t=now))
        await rec.seal(rec.open[robot])
    store.db.execute("update incident set t = t - 400 * 86400 where robot = 'r1'")

    gone = rec.prune(keep_days=365, max_bytes=10**9)
    assert gone == [r["id"] for r in store.incidents() if r["robot"] == "r1"]
    assert (nas / f"{gone[0]}.rbox").exists()
    assert not (tmp_path / "inc" / f"{gone[0]}.rbox").exists()
    assert rec.prune(keep_days=365, max_bytes=10**9) == []


@pytest.mark.skipif(os.name != "posix", reason="file modes")
def test_a_key_others_can_read_is_refused(tmp_path):
    path = tmp_path / "site.key"
    load_key(path)
    path.chmod(0o644)
    with pytest.raises(PermissionError):
        load_key(path)
