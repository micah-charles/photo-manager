from __future__ import annotations

import unittest
import base64
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from photovault.database.connection import connect
from photovault.pairing.trusted import list_trusted_android_devices, trust_android_device

from photovault.pairing.protocol import PairingError, PairingSessionStore, run_noise_xx_in_memory, sas_for_handshake, transfer_session_token
from photovault.pairing.discovery import AndroidDiscoveryService, DiscoveredAndroid


class PairingTests(unittest.TestCase):
    def test_noise_xx_peers_derive_same_sas(self) -> None:
        desktop_sas, android_sas, _ = run_noise_xx_in_memory()
        self.assertEqual(desktop_sas, android_sas)
        self.assertRegex(desktop_sas, r"^\d{3} \d{3}$")

    def test_vendored_java_noise_responder_interops(self) -> None:
        root = Path(__file__).parents[1]
        source_root = root / "android-companion/third_party/noise-java/src/main/java"
        responder = root / "tests/java/NoiseHandshakeResponder.java"
        sources = [str(path) for path in source_root.rglob("*.java")] + [str(responder)]
        with TemporaryDirectory() as temp:
            out = Path(temp)
            subprocess.run(["javac", "-source", "8", "-target", "8", "-d", str(out), *sources], check=True, capture_output=True)
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
            from noise.connection import Keypair, NoiseConnection
            initiator = NoiseConnection.from_name(b"Noise_XX_25519_ChaChaPoly_SHA256")
            initiator.set_as_initiator(); initiator.set_prologue(b"photovault-pairing-v1")
            initiator.set_keypair_from_private_bytes(Keypair.STATIC, X25519PrivateKey.generate().private_bytes_raw())
            initiator.start_handshake()
            first = bytes(initiator.write_message())
            process = subprocess.Popen(["java", "-cp", str(out), "NoiseHandshakeResponder"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            assert process.stdin and process.stdout
            process.stdin.write(base64.b64encode(first).decode() + "\n"); process.stdin.flush()
            second = base64.b64decode(process.stdout.readline().strip())
            initiator.read_message(second)
            third = bytes(initiator.write_message())
            process.stdin.write(base64.b64encode(third).decode() + "\n"); process.stdin.flush()
            java_hash = base64.b64decode(process.stdout.readline().strip())
            java_session_token = process.stdout.readline().strip()
            process.wait(timeout=10)
            process.stdin.close(); process.stdout.close()
            self.assertEqual(initiator.get_handshake_hash(), java_hash)
            self.assertEqual(transfer_session_token(initiator.get_handshake_hash()), java_session_token)

    def test_sas_changes_for_different_transcript(self) -> None:
        self.assertNotEqual(sas_for_handshake(b"a" * 32), sas_for_handshake(b"b" * 32))

    def test_transfer_session_credential_is_deterministic_and_opaque(self) -> None:
        first = transfer_session_token(b"a" * 32)
        self.assertEqual(first, transfer_session_token(b"a" * 32))
        self.assertNotEqual(first, transfer_session_token(b"b" * 32))
        self.assertNotIn("a" * 32, first)

    def test_both_sides_must_confirm(self) -> None:
        session = PairingSessionStore().start("android-1", "Charles Pixel")
        session.set_handshake(b"x" * 32, "fingerprint")
        session.confirm("local")
        self.assertEqual(session.state, "LOCAL_CONFIRMED")
        session.confirm("remote")
        self.assertEqual(session.state, "PAIRED")

    def test_expired_session_cannot_confirm(self) -> None:
        session = PairingSessionStore().start("android-1", "Charles Pixel")
        session.expires_at = 0
        with self.assertRaises(PairingError): session.set_handshake(b"x" * 32, "fingerprint")

    def test_pairing_is_rate_limited_after_failures(self) -> None:
        store = PairingSessionStore()
        for _ in range(5): store.fail(store.start("android-1", "Charles Pixel").id, "cancelled")
        with self.assertRaises(PairingError): store.start("android-1", "Charles Pixel")

    def test_trusted_device_pins_identity_and_uses_stable_source(self) -> None:
        with TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "catalog.db")
            source_id = trust_android_device(connection, device_id="install-1", display_name="Charles Pixel", public_key_fingerprint="abc", credential_reference_id="desktop-noise-static-v1")
            self.assertEqual(source_id, trust_android_device(connection, device_id="install-1", display_name="Charles Pixel", public_key_fingerprint="abc", credential_reference_id="desktop-noise-static-v1"))
            self.assertEqual(len(list_trusted_android_devices(connection)), 1)
            with self.assertRaises(ValueError): trust_android_device(connection, device_id="install-1", display_name="Charles Pixel", public_key_fingerprint="changed", credential_reference_id="desktop-noise-static-v1")

    def test_discovery_removes_the_exact_service_when_models_match(self) -> None:
        service = AndroidDiscoveryService()
        service._devices["install-1"] = DiscoveredAndroid("install-1", "Pixel 8 Pro", "192.168.1.10", 8765)
        service._devices["install-2"] = DiscoveredAndroid("install-2", "Pixel 8 Pro", "192.168.1.11", 8765)
        service._service_devices["PhotoVault-install-1._photovault._tcp.local."] = "install-1"
        service._service_devices["PhotoVault-install-2._photovault._tcp.local."] = "install-2"
        service._remove("PhotoVault-install-1._photovault._tcp.local.")
        self.assertEqual(["install-2"], list(service._devices))
