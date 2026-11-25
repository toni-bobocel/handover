"""HTTPS on a network with no public DNS and no route to a certificate authority.

The site's IT can drop their own certificate in data/tls/. Without one, the
core makes a self-signed certificate on first start, for the names and
addresses listed in fleet.toml, and logs its fingerprint so whoever installs
the browsers can check it once and trust it.
"""

import datetime as dt
import hashlib
import ipaddress
import logging
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

log = logging.getLogger(__name__)


def ensure(folder: Path, names: list[str]) -> tuple[Path, Path]:
    cert, key = folder / "cert.pem", folder / "key.pem"
    if not cert.exists():
        folder.mkdir(parents=True, exist_ok=True)
        _self_signed(cert, key, names or ["localhost"])
    pem = cert.read_bytes()
    der = x509.load_pem_x509_certificate(pem).public_bytes(serialization.Encoding.DER)
    log.info("https certificate sha256 %s", hashlib.sha256(der).hexdigest())
    return cert, key


def _san(name: str) -> x509.GeneralName:
    try:
        return x509.IPAddress(ipaddress.ip_address(name))
    except ValueError:
        return x509.DNSName(name)


def _self_signed(cert_path: Path, key_path: Path, names: list[str]) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, names[0]),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "handover"),
    ])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        # browsers cap certificate life at about two years; renewing means deleting the files
        .not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName([_san(n) for n in {*names, "localhost", "127.0.0.1"}]), False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ))
    key_path.chmod(0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
