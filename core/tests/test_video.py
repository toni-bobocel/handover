import time
import zipfile
from datetime import datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from handover.blackbox import Recorder
from handover.blackbox.bundle import verify
from handover.blackbox.video import STAMP, segments
from handover.model import Event, Telemetry
from handover.store import Store


def clip(folder, camera, t):
    name = datetime.fromtimestamp(t).astimezone().strftime(STAMP) + ".mp4"
    (folder / camera).mkdir(parents=True, exist_ok=True)
    (folder / camera / name).write_bytes(b"\x00\x00\x00\x18ftypiso6" + name.encode())
    return name


def test_only_segments_overlapping_the_window(tmp_path):
    now = time.time()
    names = [clip(tmp_path, "cam", now + d) for d in (-40, -10, -1.5, 5, 40)]
    got = segments(tmp_path, "cam", now - 10, now + 10)
    assert sorted(got) == [f"video/{n}" for n in names[1:4]]
    assert segments(tmp_path, "nothing", now - 10, now + 10) == {}


async def test_sealed_bundle_carries_the_camera_and_still_verifies(bus, tmp_path):
    key = Ed25519PrivateKey.generate()
    rec = Recorder(bus, Store(tmp_path / "db"), key, tmp_path / "inc", before=5, after=0,
                   cameras={"r1": "cam-r1"}, recordings=tmp_path / "rec")
    now = time.time()
    clip(tmp_path / "rec", "cam-r1", now - 3)
    rec.take(Telemetry("r1", 0, 0, 0, t=now))
    rec.take(Event("estop", "r1", t=now))
    path = await rec.seal(rec.open["r1"])
    assert verify(path, key.public_key()) == []
    with zipfile.ZipFile(path) as z:
        [mp4] = [n for n in z.namelist() if n.endswith(".mp4")]
        assert z.getinfo(mp4).compress_type == zipfile.ZIP_STORED
