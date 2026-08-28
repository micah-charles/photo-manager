from __future__ import annotations

import sys

from .fallback import PathVolumeProvider


def default_volume_provider():
    if sys.platform == "darwin":
        from .macos.volume import MacOSVolumeProvider

        return MacOSVolumeProvider()
    if sys.platform == "win32":
        from .windows.volume import WindowsVolumeProvider

        return WindowsVolumeProvider()
    return PathVolumeProvider()
