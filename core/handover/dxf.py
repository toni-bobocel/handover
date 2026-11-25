"""Walls and racks from an architect's DXF, as plain line segments.

Only ASCII DXF, and only LINE and LWPOLYLINE: that is what floor plans are
made of, and anything fancier (blocks, hatches, dimensions) is noise on a
plan someone reads at a glance. Coordinates are scaled to metres, shifted so
the drawing starts at 0, 0, and flipped, since DXF y points up and the plan's
points down.
"""

import json
from pathlib import Path

Segment = tuple[float, float, float, float]


def _pairs(text: str):
    lines = text.splitlines()
    for i in range(0, len(lines) - 1, 2):
        yield lines[i].strip(), lines[i + 1].strip()


def read(path: Path, scale: float = 1.0, layers: set[str] | None = None) -> list[Segment]:
    segs: list[Segment] = []
    entity, layer, pts, closed = None, "", [], False
    line: dict[str, float] = {}

    def flush():
        if layers and layer not in layers:
            return
        if entity == "LINE" and len(line) == 4:
            segs.append((line["10"], line["20"], line["11"], line["21"]))
        elif entity == "LWPOLYLINE" and len(pts) > 1:
            ring = pts + [pts[0]] if closed else pts
            segs.extend((a[0], a[1], b[0], b[1]) for a, b in zip(ring, ring[1:], strict=False))

    in_entities = False
    for code, value in _pairs(path.read_text(encoding="utf-8", errors="replace")):
        if code == "2" and value == "ENTITIES":
            in_entities = True
            continue
        if not in_entities:
            continue
        if code == "0":
            flush()
            if value == "ENDSEC":
                break
            entity, layer, pts, closed, line = value, "", [], False, {}
        elif code == "8":
            layer = value
        elif entity == "LINE" and code in ("10", "20", "11", "21"):
            line[code] = float(value)
        elif entity == "LWPOLYLINE":
            if code == "10":
                pts.append([float(value), 0.0])
            elif code == "20" and pts:
                pts[-1][1] = float(value)
            elif code == "70":
                closed = bool(int(value) & 1)

    if not segs:
        return []
    xs = [v for s in segs for v in (s[0], s[2])]
    ys = [v for s in segs for v in (s[1], s[3])]
    x0, y1 = min(xs), max(ys)
    return [
        (round((a - x0) * scale, 3), round((y1 - b) * scale, 3), round((c - x0) * scale, 3), round((y1 - d) * scale, 3))
        for a, b, c, d in segs
    ]


def save(segs: list[Segment], out: Path) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(segs), encoding="utf-8")
    w = max((max(s[0], s[2]) for s in segs), default=0)
    h = max((max(s[1], s[3]) for s in segs), default=0)
    return {"segments": len(segs), "width": round(w, 2), "height": round(h, 2)}
