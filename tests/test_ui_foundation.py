from __future__ import annotations

import unittest
import time
import tempfile
from pathlib import Path
from unittest.mock import patch

from photovault.ui.spec import NAVIGATION_GROUPS, NAVIGATION_ITEMS
from photovault.database.connection import connect
from photovault.catalog.scanner import register_volume
from photovault.platform.base import VolumeIdentity


class UIFoundationTests(unittest.TestCase):
    def test_integrity_first_navigation_contract(self) -> None:
        self.assertEqual(
            NAVIGATION_ITEMS,
            (
                "Dashboard", "Library", "Collections", "People", "Disks", "Android Devices", "Backup Sets", "Scan", "Redundancy Audit",
                "Reconciliation", "Folder Safety Audit", "Copy Plans", "Quarantine", "Operations",
                "Catalog Recovery", "Timeline", "Favourites", "Visual Duplicates", "Places",
            ),
        )

    def test_user_navigation_groups_preserve_every_existing_page(self) -> None:
        grouped_pages = tuple(page for _group, pages in NAVIGATION_GROUPS for page in pages)
        self.assertEqual(set(grouped_pages), set(NAVIGATION_ITEMS))
        self.assertEqual(len(grouped_pages), len(set(grouped_pages)))

    def test_gui_module_has_clear_optional_dependency_behavior(self) -> None:
        from photovault.ui import main_window

        if not main_window.QT_AVAILABLE:
            with self.assertRaisesRegex(RuntimeError, "PySide6 is not installed"):
                main_window._require_qt()

    def test_android_page_exposes_stateful_backup_status(self) -> None:
        from photovault.ui import main_window

        if not main_window.QT_AVAILABLE:
            self.skipTest("PySide6 is not installed")
        from PySide6.QtWidgets import QApplication

        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "catalog.db")
            app = QApplication.instance() or QApplication([])
            window = main_window.MainWindow(connection)
            window._select_page("Android Devices")
            self.assertEqual(window.android_backup_status.text(), "Not connected")
            window.android_backup_status.setText("Phone connected")
            self.assertEqual(window.android_backup_status.text(), "Phone connected")
            window.close()
            connection.close()

    def test_scan_uses_a_worker_thread_for_file_backed_catalog(self) -> None:
        from photovault.ui import main_window

        if not main_window.QT_AVAILABLE:
            self.skipTest("PySide6 is not installed")
        from PySide6.QtWidgets import QApplication

        class FixedProvider:
            def identify(self, path: Path) -> VolumeIdentity:
                return VolumeIdentity("ui-test", "ui-test-disk", "ui-test-disk")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            root.mkdir()
            (root / "clip.mp4").write_bytes(b"test-video")
            connection = connect(Path(temp) / "catalog.db")
            volume_id = register_volume(connection, root, FixedProvider())
            app = QApplication.instance() or QApplication([])
            window = main_window.MainWindow(connection)
            window.scan_volume_id.setText(volume_id)
            window.scan_root.setText(str(root))
            window._scan()
            deadline = time.monotonic() + 5
            while window._scan_thread is not None and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
            self.assertIsNone(window._scan_thread)
            self.assertIn("Completed", window.scan_result.text())
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM asset_locations").fetchone()[0], 1)
            window.close()
            connection.close()

    def test_gui_can_register_disk_and_create_backup_set(self) -> None:
        from photovault.ui import main_window

        if not main_window.QT_AVAILABLE:
            self.skipTest("PySide6 is not installed")
        from PySide6.QtWidgets import QApplication

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "disk"
            root.mkdir()
            connection = connect(Path(temp) / "catalog.db")
            app = QApplication.instance() or QApplication([])
            window = main_window.MainWindow(connection)
            window.disk_root.setText(str(root))
            window._register_disk()
            volume_id = connection.execute("SELECT id FROM volumes").fetchone()[0]
            self.assertIn("Registered", window.disk_result.text())
            window.backup_set_name.setText("Family Photos")
            window._create_backup_set()
            set_id = connection.execute("SELECT id FROM backup_sets").fetchone()[0]
            self.assertEqual(window.member_set_id.text(), set_id)
            window.member_volume_id.setText(volume_id)
            window.member_role.setText("PRIMARY")
            window._add_backup_member()
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM backup_set_members").fetchone()[0], 1)
            window.close()
            connection.close()

    def test_gui_executes_a_confirmed_copy_plan_in_background(self) -> None:
        from photovault.ui import main_window

        if not main_window.QT_AVAILABLE:
            self.skipTest("PySide6 is not installed")
        from PySide6.QtWidgets import QApplication, QMessageBox
        from photovault.backup.sets import add_member, create_backup_set
        from photovault.catalog.scanner import register_volume, scan_volume

        class FixedProvider:
            def __init__(self, name: str):
                self.name = name
            def identify(self, path: Path) -> VolumeIdentity:
                return VolumeIdentity("ui-copy", self.name, self.name)

        with tempfile.TemporaryDirectory() as temp:
            main_root = Path(temp) / "main"
            backup_root = Path(temp) / "backup"
            main_root.mkdir(); backup_root.mkdir()
            (main_root / "photo.mp4").write_bytes(b"important")
            connection = connect(Path(temp) / "catalog.db")
            main_id = register_volume(connection, main_root, FixedProvider("main"))
            backup_id = register_volume(connection, backup_root, FixedProvider("backup"))
            scan_volume(connection, main_id, main_root)
            scan_volume(connection, backup_id, backup_root)
            set_id = create_backup_set(connection, "UI copy set")
            add_member(connection, set_id, main_id, "PRIMARY")
            add_member(connection, set_id, backup_id, "BACKUP")
            app = QApplication.instance() or QApplication([])
            window = main_window.MainWindow(connection)
            window.copy_set_id.setText(set_id)
            window._build_copy_plan()
            with patch.object(main_window.QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                window._execute_copy_plan()
            deadline = time.monotonic() + 5
            while window._operation_thread is not None and time.monotonic() < deadline:
                app.processEvents(); time.sleep(0.01)
            self.assertIsNone(window._operation_thread)
            self.assertEqual((backup_root / "photo.mp4").read_bytes(), b"important")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM verification_history WHERE result='VERIFIED'").fetchone()[0], 1)
            window.close(); connection.close()

    def test_gui_can_undo_completed_quarantine_in_background(self) -> None:
        from photovault.ui import main_window

        if not main_window.QT_AVAILABLE:
            self.skipTest("PySide6 is not installed")
        from PySide6.QtWidgets import QApplication, QMessageBox
        from photovault.backup.quarantine import build_quarantine_plan, execute_quarantine_plan
        from photovault.catalog.scanner import register_volume, scan_volume

        class FixedProvider:
            def identify(self, path: Path) -> VolumeIdentity:
                return VolumeIdentity("ui-undo", "undo-disk", "undo-disk")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "photos"; root.mkdir()
            source = root / "photo.mp4"; source.write_bytes(b"restore me")
            connection = connect(Path(temp) / "catalog.db")
            volume_id = register_volume(connection, root, FixedProvider())
            scan_volume(connection, volume_id, root)
            quarantine_plan = build_quarantine_plan(connection, [source], "UI undo test")
            self.assertEqual(execute_quarantine_plan(connection, quarantine_plan)["status"], "COMPLETED")
            app = QApplication.instance() or QApplication([])
            window = main_window.MainWindow(connection)
            window.undo_operation_id.setText(quarantine_plan.operation_id)
            with patch.object(main_window.QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                window._undo_quarantine()
            deadline = time.monotonic() + 5
            while window._operation_thread is not None and time.monotonic() < deadline:
                app.processEvents(); time.sleep(0.01)
            self.assertIsNone(window._operation_thread)
            self.assertEqual(source.read_bytes(), b"restore me")
            window.close(); connection.close()


if __name__ == "__main__":
    unittest.main()
