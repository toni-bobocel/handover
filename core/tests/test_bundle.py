import io
import json
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from handover.blackbox import bundle
from handover.blackbox.ring import Ring


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def sealed(tmp_path, key):
    records = [{"type": "telemetry", "robot": "r1", "x": i * 0.1, "y": 0.0, "t": 100 + i} for i in range(50)]
    records.insert(20, {"type": "event", "kind": "estop", "robot": "r1", "detail": {}, "t": 120})
    incident = {"id": "x", "robot": "r1", "kind": "estop", "t": 120, "before": 30, "after": 30}
    path = tmp_path / "x.rbox"
    bundle.write(path, incident, records, key)
    return path


def rewrite(path, name, change):
    """Rebuild the zip with one member changed, the way someone editing it by hand would."""
    with zipfile.ZipFile(path) as z:
        files = {n: z.read(n) for n in z.namelist()}
    files[name] = change(files[name])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, data in files.items():
            z.writestr(n, data)
    return buf.getvalue()


def test_intact_bundle_verifies(sealed, key):
    assert bundle.verify(sealed, key.public_key()) == []


def test_edited_record_is_caught(sealed, key):
    def nudge(data):
        lines = data.decode().splitlines()
        rec = json.loads(lines[10])
        rec["x"] += 0.5
        lines[10] = json.dumps(rec)
        return ("\n".join(lines) + "\n").encode()

    problems = bundle.verify(rewrite(sealed, "telemetry.jsonl", nudge), key.public_key())
    assert "telemetry.jsonl was modified" in problems
    assert any("record 11" in p for p in problems)


def test_deleted_record_breaks_the_chain(sealed, key):
    def drop(data):
        lines = data.decode().splitlines()
        del lines[20]
        return ("\n".join(lines) + "\n").encode()

    problems = bundle.verify(rewrite(sealed, "telemetry.jsonl", drop), key.public_key())
    assert any("chain broken before record 21" in p for p in problems)


def test_truncated_tail_is_caught_even_with_a_fixed_manifest_hash(sealed, key):
    # an editor who also fixes the file hash in the manifest still has to forge the signature
    def cut(data):
        return b"".join(data.splitlines(keepends=True)[:-5])

    problems = bundle.verify(rewrite(sealed, "telemetry.jsonl", cut), key.public_key())
    assert "records missing from the end of the chain" in problems


def test_resigned_with_another_key_is_caught(sealed, key):
    other = Ed25519PrivateKey.generate()

    def resign(_):
        with zipfile.ZipFile(sealed) as z:
            return other.sign(z.read("manifest.json")).hex().encode()

    data = rewrite(sealed, "manifest.sig", resign)
    assert "manifest signature does not match" in bundle.verify(data, key.public_key())


def test_cli_exit_codes(sealed, key, tmp_path, capsys):
    pub = tmp_path / "site.pub"
    pub.write_bytes(bundle.public_pem(key.public_key()))
    assert bundle.verify_cli([str(sealed), "--key", str(pub)]) == 0
    other = tmp_path / "other.pub"
    other.write_bytes(bundle.public_pem(Ed25519PrivateKey.generate().public_key()))
    assert bundle.verify_cli([str(sealed), "--key", str(other)]) == 1
    assert "different key" in capsys.readouterr().out


def test_ring_keeps_only_its_window():
    r = Ring(seconds=10)
    for t in range(30):
        r.push(float(t), {"t": t})
    assert len(r) == 11
    assert [x["t"] for x in r.window(25, 27)] == [25, 26, 27]


def test_bundle_carries_a_readable_pdf(sealed, key):
    with zipfile.ZipFile(sealed) as z:
        body = z.read("report.pdf")
        manifest = json.loads(z.read("manifest.json"))
    assert body.startswith(b"%PDF-1.4") and body.rstrip().endswith(b"%%EOF")
    assert "report.pdf" in manifest["files"]
    # the cross-reference table must point at real objects, or viewers refuse the file
    xref = int(body.rsplit(b"startxref", 1)[1].split()[0])
    assert body[xref:xref + 4] == b"xref"
