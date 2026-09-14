import unittest
import subprocess
import socket
import ssl
import threading
from tempfile import TemporaryDirectory
from pathlib import Path
from datetime import datetime, timedelta, timezone

from photovault.database.connection import connect
from photovault.pairing.v2 import (
    AndroidPairingState,
    DesktopPairingState,
    PAIRING_V2_PROTOCOL,
    pairing_v2_digest,
    pairing_v2_sas,
    PairingRequestStore,
)
from photovault.pairing.tls import TLSIdentityError, connect_candidate, connect_trusted


class PairingV2Tests(unittest.TestCase):
    def test_protocol_is_distinct(self) -> None:
        self.assertEqual(PAIRING_V2_PROTOCOL, "photovault-pairing-v2")

    def test_canonical_sas_is_deterministic_and_six_digits(self) -> None:
        kwargs = {
            "android_fingerprint": "android-fingerprint-01",
            "desktop_fingerprint": "desktop-fingerprint-01",
            "nonce": bytes.fromhex("00112233445566778899aabbccddeeff"),
        }
        self.assertEqual(
            pairing_v2_digest(**kwargs).hex(),
            "2b7dbdbb99167feab88e5f036432c755a8a097f83c4980eb22da155e942283cf",
        )
        value = pairing_v2_sas(**kwargs)
        self.assertRegex(value, r"^[0-9]{6}$")
        self.assertEqual(value, pairing_v2_sas(**kwargs))

    def test_java_and_python_sas_vector_match(self) -> None:
        root = Path(__file__).parents[1]
        source = root / "tests/java/PairingV2Vector.java"
        with TemporaryDirectory() as directory:
            subprocess.run(["javac", "-source", "8", "-target", "8", "-d", directory, str(source)], check=True, capture_output=True)
            output = subprocess.check_output([
                "java", "-cp", directory, "PairingV2Vector",
                "android-fingerprint-01", "desktop-fingerprint-01",
                "00112233445566778899aabbccddeeff",
            ], text=True).strip().split()
        kwargs = {
            "android_fingerprint": "android-fingerprint-01",
            "desktop_fingerprint": "desktop-fingerprint-01",
            "nonce": bytes.fromhex("00112233445566778899aabbccddeeff"),
        }
        self.assertEqual(output[0], pairing_v2_digest(**kwargs).hex())
        self.assertEqual(output[1], pairing_v2_sas(**kwargs))

    def test_state_names_are_explicit(self) -> None:
        self.assertEqual(AndroidPairingState.PAIRED.value, "PAIRED")
        self.assertEqual(DesktopPairingState.IDENTITY_CHANGED.value, "IDENTITY_CHANGED")

    def test_pairing_request_survives_new_connection(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.db"
            first = connect(path)
            request = PairingRequestStore(first).create(
                pair_request_id="req-1", device_id="android-1",
                display_name="Charles Pixel", remote_address="192.0.2.1:8765",
                android_certificate_fingerprint="android-cert",
                desktop_certificate_fingerprint="desktop-cert",
                pairing_nonce=b"nonce", sas="123456",
            )
            first.close()
            second = connect(path)
            restored = PairingRequestStore(second).get("req-1")
            self.assertEqual(request, restored)
            PairingRequestStore(second).expire("req-1", "service restarted")
            self.assertEqual(PairingRequestStore(second).get("req-1").state, "PAIRING_EXPIRED")
            second.close()

    def test_tls_candidate_and_pinned_connection_are_tls13_only(self) -> None:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(minutes=5))
            .sign(key, hashes.SHA256()))
        with TemporaryDirectory() as directory:
            cert_path = Path(directory) / "cert.pem"; key_path = Path(directory) / "key.pem"
            cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
            cert_path.write_bytes(cert_pem)
            key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.minimum_version = ssl.TLSVersion.TLSv1_3; server_context.maximum_version = ssl.TLSVersion.TLSv1_3
            server_context.load_cert_chain(cert_path, key_path)

            def run_server(listener: socket.socket) -> None:
                raw, _ = listener.accept()
                with server_context.wrap_socket(raw, server_side=True) as connection: connection.recv(1)

            listener = socket.socket(); listener.bind(("127.0.0.1", 0)); listener.listen(1)
            port = listener.getsockname()[1]; worker = threading.Thread(target=run_server, args=(listener,), daemon=True); worker.start()
            candidate, identity = connect_candidate("127.0.0.1", port)
            self.assertEqual(candidate.version(), "TLSv1.3"); candidate.sendall(b"x"); candidate.close(); worker.join(timeout=2); listener.close()

            listener = socket.socket(); listener.bind(("127.0.0.1", 0)); listener.listen(1)
            port = listener.getsockname()[1]; worker = threading.Thread(target=run_server, args=(listener,), daemon=True); worker.start()
            trusted = connect_trusted("127.0.0.1", port, certificate_pem=identity.certificate_pem, expected_fingerprint=identity.fingerprint)
            self.assertEqual(trusted.version(), "TLSv1.3"); trusted.sendall(b"x"); trusted.close(); worker.join(timeout=2); listener.close()
            with self.assertRaises(TLSIdentityError):
                connect_trusted("127.0.0.1", port, certificate_pem=identity.certificate_pem, expected_fingerprint="00" * 32)


if __name__ == "__main__":
    unittest.main()
