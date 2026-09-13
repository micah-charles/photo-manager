"""OS-backed credential abstraction for desktop pairing identities."""
from __future__ import annotations

from dataclasses import dataclass, field


class CredentialStore:
    def get(self, reference_id: str) -> bytes | None: raise NotImplementedError
    def put(self, reference_id: str, value: bytes) -> None: raise NotImplementedError
    def delete(self, reference_id: str) -> None: raise NotImplementedError


class KeyringCredentialStore(CredentialStore):
    """Uses macOS Keychain/Windows Credential Manager through keyring."""
    def __init__(self, service: str = "PhotoManager") -> None: self.service = service
    def get(self, reference_id: str) -> bytes | None:
        import keyring
        value = keyring.get_password(self.service, reference_id)
        return value.encode("utf-8") if value is not None else None
    def put(self, reference_id: str, value: bytes) -> None:
        import keyring
        keyring.set_password(self.service, reference_id, value.decode("utf-8"))
    def delete(self, reference_id: str) -> None:
        import keyring
        try: keyring.delete_password(self.service, reference_id)
        except keyring.errors.PasswordDeleteError: pass


@dataclass
class TestCredentialStore(CredentialStore):
    values: dict[str, bytes] = field(default_factory=dict)
    def get(self, reference_id: str) -> bytes | None: return self.values.get(reference_id)
    def put(self, reference_id: str, value: bytes) -> None: self.values[reference_id] = value
    def delete(self, reference_id: str) -> None: self.values.pop(reference_id, None)
