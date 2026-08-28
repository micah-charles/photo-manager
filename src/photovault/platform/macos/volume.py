from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

from ..base import VolumeIdentity
from ..fallback import PathVolumeProvider


class MacOSVolumeProvider:
    """Resolve the containing macOS volume through diskutil, without leaking it into core logic."""

    def __init__(self, runner=subprocess.run) -> None:
        self._runner = runner

    def identify(self, path: Path) -> VolumeIdentity:
        root = path.expanduser().resolve()
        try:
            result = self._runner(
                ["diskutil", "info", "-plist", str(root)],
                check=True,
                capture_output=True,
            )
            info = plistlib.loads(result.stdout)
            volume_uuid = info.get("VolumeUUID") or info.get("APFSVolumeGroupUUID")
            if not volume_uuid:
                raise ValueError("diskutil did not return a volume UUID")
            return VolumeIdentity(
                identity_kind="macos_volume_uuid",
                identity_value=str(volume_uuid).lower(),
                display_name=str(info.get("VolumeName") or root.name or root),
                filesystem=info.get("FileSystemPersonality") or info.get("FilesystemType"),
                capacity_bytes=int(info["TotalSize"]) if info.get("TotalSize") is not None else None,
            )
        except (OSError, subprocess.CalledProcessError, plistlib.InvalidFileException, ValueError, TypeError, KeyError):
            # A provider failure must not prevent cataloguing; the fallback is explicit in metadata.
            return PathVolumeProvider().identify(root)
