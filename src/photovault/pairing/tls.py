"""TLS 1.3 transport helpers for Pairing v2.

Candidate pairing may inspect an untrusted self-signed certificate, but only
after an explicit fingerprint check.  Trusted connections build a context
from the pinned certificate and use normal certificate validation.
"""
from __future__ import annotations

import hashlib
import socket
import ssl
from dataclasses import dataclass


class TLSIdentityError(RuntimeError):
    pass


def certificate_fingerprint(certificate_der: bytes) -> str:
    return hashlib.sha256(certificate_der).hexdigest()


@dataclass(frozen=True)
class PeerIdentity:
    certificate_pem: str
    fingerprint: str


def _tls13_context(*, verify: bool, trusted_certificate_pem: str | None = None) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.maximum_version = ssl.TLSVersion.TLSv1_3
    if verify:
        if not trusted_certificate_pem:
            raise ValueError("trusted TLS connections require a pinned certificate")
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = False
        context.load_verify_locations(cadata=trusted_certificate_pem)
    else:
        # This mode is only for first-use pairing, and the caller must verify
        # the returned certificate fingerprint before using the connection.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def connect_candidate(host: str, port: int, *, timeout: float = 10.0) -> tuple[ssl.SSLSocket, PeerIdentity]:
    """Connect once to an untrusted candidate and return its certificate identity."""
    context = _tls13_context(verify=False)
    raw = socket.create_connection((host, port), timeout=timeout)
    connection = context.wrap_socket(raw, server_hostname=host)
    certificate_der = connection.getpeercert(binary_form=True)
    if not certificate_der:
        connection.close()
        raise TLSIdentityError("Android endpoint did not present a certificate")
    certificate_pem = ssl.DER_cert_to_PEM_cert(certificate_der)
    return connection, PeerIdentity(certificate_pem, certificate_fingerprint(certificate_der))


def connect_trusted(host: str, port: int, *, certificate_pem: str,
                    expected_fingerprint: str, timeout: float = 10.0) -> ssl.SSLSocket:
    """Connect with TLS validation and an explicit pinned certificate check."""
    actual = certificate_fingerprint(ssl.PEM_cert_to_DER_cert(certificate_pem))
    if actual != expected_fingerprint:
        raise TLSIdentityError("configured certificate fingerprint does not match pinned identity")
    context = _tls13_context(verify=True, trusted_certificate_pem=certificate_pem)
    raw = socket.create_connection((host, port), timeout=timeout)
    try:
        connection = context.wrap_socket(raw, server_hostname=host)
        observed = certificate_fingerprint(connection.getpeercert(binary_form=True))
        if observed != expected_fingerprint:
            connection.close()
            raise TLSIdentityError("peer certificate does not match pinned identity")
        return connection
    except Exception:
        raw.close()
        raise
