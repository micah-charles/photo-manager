from __future__ import annotations

from pathlib import Path

from .base import VolumeIdentity


class PathVolumeProvider:
    """Portable fallback used until a platform exposes a stable volume identifier."""

    def identify(self, path: Path) -> VolumeIdentity:
        root = path.expanduser().resolve()
        return VolumeIdentity(
            identity_kind="path_fallback",
            identity_value=str(root),
            display_name=root.name or str(root),
        )
