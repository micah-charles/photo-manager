from __future__ import annotations

import ctypes
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photovault.platform.windows.volume import WindowsVolumeProvider


class FakeKernel32:
    def GetVolumeInformationW(self, root, volume_name, volume_name_length, serial, max_component, flags, filesystem, filesystem_length):
        volume_name.value = "PhotoVault Test Disk"
        filesystem.value = "NTFS"
        serial._obj.value = 0x1234ABCD
        return 1


class WindowsProviderTests(unittest.TestCase):
    def test_uses_volume_serial_and_name_when_windows_api_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(ctypes, "WinDLL", return_value=FakeKernel32(), create=True):
                identity = WindowsVolumeProvider().identify(Path(temp))
        self.assertEqual(identity.identity_kind, "windows_volume_serial")
        self.assertEqual(identity.identity_value, "1234abcd")
        self.assertEqual(identity.display_name, "PhotoVault Test Disk")
        self.assertEqual(identity.filesystem, "NTFS")

    def test_drive_letter_is_not_part_of_stable_identity(self) -> None:
        provider = WindowsVolumeProvider()
        with patch.object(ctypes, "WinDLL", return_value=FakeKernel32(), create=True):
            first = provider.identify(Path("E:/Photos"))
            second = provider.identify(Path("F:/Photos"))
        self.assertEqual(first.identity_value, second.identity_value)

    def test_degrades_to_path_fallback_when_windows_api_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(ctypes, "WinDLL", side_effect=OSError("not Windows"), create=True):
                identity = WindowsVolumeProvider().identify(Path(temp))
        self.assertEqual(identity.identity_kind, "path_fallback")
        self.assertTrue(identity.identity_value)


if __name__ == "__main__":
    unittest.main()
