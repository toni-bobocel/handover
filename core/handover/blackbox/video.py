"""The video half of the ring buffer lives in MediaMTX's recordings folder,
a RAM volume where it writes each camera in 2 s fMP4 segments and deletes
them after 75 s. Sealing an incident copies the segments that overlap the
window; each segment is a playable file on its own."""

from datetime import datetime
from pathlib import Path

# the recordPath pattern in deploy/mediamtx.yml, minus the folder
STAMP = "%Y-%m-%d_%H-%M-%S-%f_%z"
SEGMENT = 2.0


def started(name: str) -> float | None:
    try:
        return datetime.strptime(name.removesuffix(".mp4"), STAMP).timestamp()
    except ValueError:
        return None


def segments(folder: Path, camera: str, start: float, end: float) -> dict[str, bytes]:
    """video/<segment>.mp4 for every segment of this camera that overlaps start..end."""
    out = {}
    cam = folder / camera
    if not cam.is_dir():
        return out
    for f in sorted(cam.glob("*.mp4")):
        t = started(f.name)
        if t is None or t + SEGMENT < start or t > end:
            continue
        try:
            out[f"video/{f.name}"] = f.read_bytes()
        except FileNotFoundError:
            # MediaMTX deleted it between the listing and the read: it was the oldest anyway
            continue
    return out
