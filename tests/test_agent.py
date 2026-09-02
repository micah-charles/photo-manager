from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from photovault.agent.service import PhotoVaultToolService
from photovault.database.connection import connect


class AgentToolTests(unittest.TestCase):
    def test_library_summary_is_read_only_and_plan_has_no_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.db"
            service = PhotoVaultToolService(catalog)
            summary = service.library_summary()
            plan = service.organize_trip_plan("Trip", "2026-08-22", "2026-08-23")
            self.assertEqual(summary["asset_count"], 0)
            self.assertEqual(plan["physical_file_changes"], 0)
            self.assertTrue(plan["requires_approval"])
            db = connect(catalog)
            try:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)
            finally:
                db.close()

    def test_mcp_stdio_lists_tools_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, "-m", "photovault.agent.mcp_server", "--catalog", str(Path(directory) / "catalog.db")]
            payload = "\n".join([
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
            ]) + "\n"
            completed = subprocess.run(command, input=payload, text=True, capture_output=True, check=True)
            lines = [json.loads(line) for line in completed.stdout.splitlines()]
            names = {tool["name"] for tool in lines[1]["result"]["tools"]}
            self.assertIn("library_summary", names)
            self.assertIn("organize_trip_plan", names)
            self.assertEqual(completed.stderr, "")
