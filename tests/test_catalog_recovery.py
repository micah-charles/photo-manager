from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photovault.catalog.recovery import backup_catalog, check_catalog_integrity
from photovault.database.connection import connect


class CatalogRecoveryTests(unittest.TestCase):
    def test_online_backup_is_consistent_and_never_overwrites_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.db"
            connection = connect(catalog)
            connection.execute(
                "INSERT INTO volumes(id, display_name, identity_kind, identity_value, first_seen, last_seen, status) "
                "VALUES ('vol_test', 'Test', 'test', 'test', datetime('now'), datetime('now'), 'CONNECTED')"
            )
            connection.commit()
            destination = root / "catalog-backup.db"
            result = backup_catalog(catalog, destination)
            self.assertEqual(result.integrity, ("ok",))
            self.assertGreater(result.bytes_written, 0)
            self.assertEqual(check_catalog_integrity(destination), ("ok",))
            restored = connect(destination)
            self.assertEqual(restored.execute("SELECT COUNT(*) FROM volumes").fetchone()[0], 1)
            restored.close()
            with self.assertRaises(FileExistsError):
                backup_catalog(catalog, destination)
            connection.close()
