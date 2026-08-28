from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class VolumeIdentity:
    identity_kind: str
    identity_value: str
    display_name: str
    filesystem: str | None = None
    capacity_bytes: int | None = None


class VolumeProvider(Protocol):
    def identify(self, path: Path) -> VolumeIdentity:
        """Return the strongest stable identity available for the volume containing path."""
