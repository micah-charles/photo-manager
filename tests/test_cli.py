from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photovault.cli import main as cli_main


class CliRegressionTests(unittest.TestCase):
    def test_register_command_is_not_shadowed_by_android_wifi_copy_import(self) -> None:
        """The general register command must remain available after Android CLI paths load."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "media"
            media.mkdir()
            output = io.StringIO()
            with patch("sys.argv", ["photovault", "--catalog", str(root / "catalog.db"), "register", str(media)]):
                with contextlib.redirect_stdout(output):
                    self.assertEqual(cli_main.main(), 0)
            self.assertTrue(output.getvalue().strip().startswith("vol_"))


if __name__ == "__main__":
    unittest.main()
