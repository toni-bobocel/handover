"""The .rbox format: a zip anyone can open, that nobody can edit quietly.

    telemetry.jsonl   every record in the window, each carrying the hash of the one before
    incident.json     what fired, when, on which robot
    report.html       the same, readable in any browser
    report.pdf        the same again, for the vendor's or the insurer's file
    manifest.json     sha256 of each file above, the head of the chain, the key fingerprint
    manifest.sig      Ed25519 signature of manifest.json
    site.pub          the public key, for convenience only: verify against the copy you were given

Deleting a line breaks the chain, editing one breaks its hash, re-hashing
everything breaks the signature.
"""

import argparse
import hashlib
import html
import io
import json
import os
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from . import pdf

GENESIS = "0" * 64


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def chain(records: list[dict]) -> tuple[list[dict], str]:
    out, prev = [], GENESIS
    for r in records:
        linked = {**r, "prev": prev}
        prev = hashlib.sha256(canonical(linked)).hexdigest()
        out.append({**linked, "hash": prev})
    return out, prev


def load_key(path: Path) -> Ed25519PrivateKey:
    if path.exists():
        if os.name == "posix" and path.stat().st_mode & 0o077:
            # anyone who can read this key can sign bundles in the site's name
            raise PermissionError(f"{path} is readable by other users; chmod 600 it")
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ))
    path.chmod(0o600)
    path.with_suffix(".pub").write_bytes(public_pem(key.public_key()))
    return key


def public_pem(pub: Ed25519PublicKey) -> bytes:
    return pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def fingerprint(pub: Ed25519PublicKey) -> str:
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def write(path: Path, incident: dict, records: list[dict], key: Ed25519PrivateKey) -> str:
    linked, head = chain(records)
    files = {
        "telemetry.jsonl": b"".join(canonical(r) + b"\n" for r in linked),
        "incident.json": json.dumps(incident, indent=2).encode(),
        "report.html": report(incident, linked, head).encode(),
        "report.pdf": pdf.report(incident, linked, head),
    }
    manifest = {
        "format": "rbox/1",
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        "chain_head": head,
        "records": len(linked),
        "key": fingerprint(key.public_key()),
    }
    mbytes = json.dumps(manifest, indent=2).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
        z.writestr("manifest.json", mbytes)
        z.writestr("manifest.sig", key.sign(mbytes).hex())
        z.writestr("site.pub", public_pem(key.public_key()))
    tmp.replace(path)
    return head


def verify(source: Path | bytes, pub: Ed25519PublicKey | None = None) -> list[str]:
    """Returns what is wrong with a bundle; an empty list means it is intact."""
    problems = []
    with zipfile.ZipFile(io.BytesIO(source) if isinstance(source, bytes) else source) as z:
        names = set(z.namelist())
        mbytes = z.read("manifest.json")
        manifest = json.loads(mbytes)
        if pub is None:
            pub = serialization.load_pem_public_key(z.read("site.pub"))
        elif fingerprint(pub) != manifest["key"]:
            problems.append("signed with a different key")
        try:
            pub.verify(bytes.fromhex(z.read("manifest.sig").decode()), mbytes)
        except (InvalidSignature, ValueError):
            problems.append("manifest signature does not match")
        for name, digest in manifest["files"].items():
            if name not in names:
                problems.append(f"{name} is missing")
            elif hashlib.sha256(z.read(name)).hexdigest() != digest:
                problems.append(f"{name} was modified")
        lines = z.read("telemetry.jsonl").decode().splitlines()

    prev = GENESIS
    for n, line in enumerate(lines, 1):
        rec = json.loads(line)
        claimed = rec.pop("hash", None)
        if rec.get("prev") != prev:
            problems.append(f"chain broken before record {n}")
            break
        if hashlib.sha256(canonical(rec)).hexdigest() != claimed:
            problems.append(f"record {n} does not match its hash")
            break
        prev = claimed
    else:
        if prev != manifest["chain_head"]:
            problems.append("records missing from the end of the chain")
    return problems


def verify_cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rbox-verify", description="Check that an incident bundle is intact.")
    p.add_argument("bundle", type=Path)
    p.add_argument("--key", type=Path, help="the site's public key (site.pub), as handed over by the site")
    a = p.parse_args(argv)
    pub = serialization.load_pem_public_key(a.key.read_bytes()) if a.key else None
    problems = verify(a.bundle, pub)
    if not a.key:
        print("note: checked against the key inside the bundle; pass --key to check who signed it")
    for line in problems:
        print(f"FAIL  {line}")
    if not problems:
        print(f"OK    {a.bundle.name}")
    return 1 if problems else 0


def _when(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%H:%M:%S.%f")[:-3]


def report(incident: dict, records: list[dict], head: str) -> str:
    track = [(r["x"], r["y"]) for r in records if r.get("type") == "telemetry"]
    events = [r for r in records if r.get("type") == "event"]
    svg = ""
    if track:
        xs, ys = [p[0] for p in track], [p[1] for p in track]
        x0, y0 = min(xs) - 1, min(ys) - 1
        w, h = max(max(xs) - x0 + 1, 2), max(max(ys) - y0 + 1, 2)
        pts = " ".join(f"{x - x0:.2f},{h - (y - y0):.2f}" for x, y in track)
        svg = (f'<svg viewBox="0 0 {w:.2f} {h:.2f}" width="420"><polyline points="{pts}" fill="none" '
               f'stroke="#111" stroke-width="{max(w, h) / 200:.3f}"/></svg>')
    rows = "".join(
        f"<tr><td>{_when(e['t'])}</td><td>{html.escape(e['kind'])}</td>"
        f"<td>{html.escape(json.dumps(e.get('detail', {})))}</td></tr>"
        for e in events
    )
    return f"""<!doctype html><meta charset="utf-8"><title>Incident {html.escape(incident['id'])}</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;max-width:760px;margin:40px auto;color:#111}}
td{{padding:2px 12px 2px 0;vertical-align:top}}code{{font-size:12px;word-break:break-all}}</style>
<h1>{html.escape(incident['robot'])}: {html.escape(incident['kind'])}</h1>
<p>{html.escape(incident.get('site', ''))}, {datetime.fromtimestamp(incident['t'], UTC):%Y-%m-%d %H:%M:%S} UTC.
{len(records)} records from {incident['before']:.0f} s before to {incident['after']:.0f} s after.</p>
{svg}
<h2>Timeline</h2><table>{rows or '<tr><td>No operator or rule events in the window.</td></tr>'}</table>
<h2>Integrity</h2><p>Chain head <code>{head}</code>. Check the bundle with
<code>rbox-verify {html.escape(incident['id'])}.rbox --key site.pub</code>.</p>
"""


if __name__ == "__main__":
    sys.exit(verify_cli())
