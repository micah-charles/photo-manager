from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

from ..base import VolumeIdentity


class WindowsVolumeProvider:
    """Use the Windows volume GUID when available, with a documented fallback."""

    def identify(self, path: Path) -> VolumeIdentity:
        root = str(path.expanduser().resolve())
        if not root.endswith("\\"):
            root += "\\"
        try:
            volume_name = ctypes.create_unicode_buffer(261)
            filesystem = ctypes.create_unicode_buffer(261)
            serial = wintypes.DWORD()
            max_component = wintypes.DWORD()
            flags = wintypes.DWORD()
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            ok = kernel32.GetVolumeInformationW(
                wintypes.LPCWSTR(root), volume_name, len(volume_name),
                ctypes.byref(serial), ctypes.byref(max_component), ctypes.byref(flags),
                filesystem, len(filesystem),
            )
            if ok:
                # Drive letters are mount locations, not volume identity: the
                # same removable disk may move from E: to F:. The filesystem
                # serial remains stable across that remount.
                identity = f"{serial.value:08x}"
                return VolumeIdentity("windows_volume_serial", identity,
                                      volume_name.value or root[:2], filesystem.value or None)
        except (AttributeError, OSError):
            pass
        return VolumeIdentity("path_fallback", root, Path(root).name or root)
