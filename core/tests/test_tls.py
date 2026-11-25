import ipaddress

from cryptography import x509

from handover.tls import ensure


def test_self_signed_covers_the_site_names(tmp_path):
    cert, key = ensure(tmp_path, ["handover.plant.local", "192.168.10.5"])
    c = x509.load_pem_x509_certificate(cert.read_bytes())
    san = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "handover.plant.local" in san.get_values_for_type(x509.DNSName)
    assert ipaddress.ip_address("192.168.10.5") in san.get_values_for_type(x509.IPAddress)
    # a second start keeps the certificate browsers were told to trust
    before = cert.read_bytes()
    ensure(tmp_path, ["other"])
    assert cert.read_bytes() == before
