"""A one- or two-page incident report as PDF, written by hand.

A PDF library would be the usual answer; this needs Helvetica, lines and a
polyline, which the format gives for free, and the image stays one
dependency lighter on a machine nobody wants to patch.
"""

import zlib
from datetime import UTC, datetime

W, H = 595, 842  # A4 in points
M = 56


def _esc(text: str) -> str:
    raw = text.encode("cp1252", "replace").decode("latin-1")
    return raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class _Page:
    def __init__(self):
        self.ops: list[str] = []
        self.y = H - M

    def text(self, s: str, size: float = 10, x: float = M, bold: bool = False, grey: float = 0) -> None:
        font = "F2" if bold else "F1"
        self.ops.append(f"{grey:.2f} g BT /{font} {size} Tf {x:.1f} {self.y:.1f} Td ({_esc(s)}) Tj ET")

    def line(self, x0: float, y0: float, x1: float, y1: float, grey: float = 0.8) -> None:
        self.ops.append(f"{grey:.2f} G 0.5 w {x0:.1f} {y0:.1f} m {x1:.1f} {y1:.1f} l S")

    def down(self, by: float) -> None:
        self.y -= by


def _wrap(s: str, width: int) -> list[str]:
    out, cur = [], ""
    for word in s.split():
        if len(cur) + len(word) + 1 > width:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return [*out, cur] if cur else out


def _when(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%H:%M:%S.%f")[:-3]


def report(incident: dict, records: list[dict], head: str) -> bytes:
    pages = [_Page()]
    p = pages[0]
    p.text("INCIDENT REPORT", 8, grey=0.45)
    p.down(26)
    p.text(f"{incident['robot']}: {incident['kind'].replace('_', ' ')}", 20, bold=True)
    p.down(20)
    when = datetime.fromtimestamp(incident["t"], UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    p.text(f"{incident.get('site', '')}, {when}", 10, grey=0.3)
    p.down(14)
    also = ", ".join(incident.get("also", []))
    p.text(f"{len(records)} records, {incident['before']:.0f} s before to {incident['after']:.0f} s after"
           + (f". Also in this window: {also}." if also else "."), 10, grey=0.3)
    p.down(26)

    track = [(r["x"], r["y"], r["t"]) for r in records if r.get("type") == "telemetry"]
    if track:
        box_w, box_h = W - 2 * M, 200
        xs, ys = [q[0] for q in track], [q[1] for q in track]
        x0, y0 = min(xs), min(ys)
        span = max(max(xs) - x0, max(ys) - y0, 2)
        k = min(box_w - 40, box_h - 40) / span
        # centre the path in its frame
        ox = M + (box_w - (max(xs) - x0) * k) / 2
        oy = (box_h - (max(ys) - y0) * k) / 2
        top = p.y
        p.line(M, top, M + box_w, top)
        p.line(M, top - box_h, M + box_w, top - box_h)
        # plan y grows downwards, PDF y upwards
        pts = [(ox + (x - x0) * k, top - oy - (y - y0) * k) for x, y, _ in track]
        path = " ".join(f"{x:.1f} {y:.1f} {'m' if i == 0 else 'l'}" for i, (x, y) in enumerate(pts))
        p.ops.append(f"0 G 1 w {path} S")
        # where the robot was when it fired
        hit = min(range(len(track)), key=lambda i: abs(track[i][2] - incident["t"]))
        hx, hy = pts[hit]
        p.ops.append(f"0.96 0.6 0.15 rg {hx - 3:.1f} {hy - 3:.1f} 6 6 re f")
        p.y = top - box_h - 14
        p.text(f"Path over the window, {span:.1f} m across. The square marks the trigger.", 8, grey=0.45)
        p.down(28)

    p.text("Timeline", 12, bold=True)
    p.down(18)
    for e in (r for r in records if r.get("type") == "event"):
        if p.y < M + 60:
            p = _Page()
            pages.append(p)
        detail = " · ".join(f"{k.replace('_', ' ')} {v}" for k, v in e.get("detail", {}).items())
        p.text(_when(e["t"]), 9, grey=0.4)
        p.text(e["kind"].replace("_", " "), 9, x=M + 80, bold=True)
        for i, chunk in enumerate(_wrap(detail, 60)):
            if i:
                p.down(12)
            p.text(chunk, 9, x=M + 210, grey=0.3)
        p.down(15)

    if p.y < M + 90:
        p = _Page()
        pages.append(p)
    p.down(14)
    p.text("Integrity", 12, bold=True)
    p.down(18)
    for line in _wrap("This report is part of a signed bundle. The telemetry inside is a SHA-256 hash chain whose "
                      "last link is below; the manifest listing every file is signed with the site's Ed25519 key. "
                      f"Check it with: rbox-verify {incident['id']}.rbox --key site.pub", 92):
        p.text(line, 9, grey=0.3)
        p.down(13)
    p.down(4)
    p.text(head, 8.5, grey=0)
    return _assemble(pages)


def _assemble(pages: list[_Page]) -> bytes:
    objs: list[bytes] = []
    n = len(pages)
    # 1 catalog, 2 pages, 3-4 fonts, then (page, content) pairs
    kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    for name in ("Helvetica", "Helvetica-Bold"):
        objs.append(f"<< /Type /Font /Subtype /Type1 /BaseFont /{name} /Encoding /WinAnsiEncoding >>".encode())
    for i, pg in enumerate(pages):
        stream = zlib.compress("\n".join(pg.ops).encode("latin-1"))
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] /Contents {6 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>".encode())
        objs.append(f"<< /Length {len(stream)} /Filter /FlateDecode >>\nstream\n".encode() + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
