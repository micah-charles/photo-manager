from __future__ import annotations

import unittest
import time
import tempfile
from pathlib import Path
from unittest.mock import patch

from photovault.ui.spec import ADVANCED_PAGE_ITEMS, NAVIGATION_GROUPS, NAVIGATION_ITEMS
from photovault.database.connection import connect
from photovault.catalog.scanner import register_volume
from photovault.platform.base import VolumeIdentity


class UIFoundationTests(unittest.TestCase):
    def test_integrity_first_navigation_contract(self) -> None:
        self.assertEqual(
            NAVIGATION_ITEMS,
            (
                "Dashboard", "Library", "Photo Viewer", "Collections", "People", "Disks", "Android Devices", "Backup Profiles", "Backup Sets", "Scan", "Redundancy Audit",
                "Reconciliation", "Folder Safety Audit", "Copy Plans", "Quarantine", "Operations",
                "Catalog Recovery", "Timeline", "Favourites", "Visual Duplicates", "Places", "Categories", "Backup Health", "Advanced Tools", "Settings",
            ),
        )

    def test_user_navigation_groups_preserve_every_existing_page(self) -> None:
        grouped_pages = tuple(page for _group, pages in NAVIGATION_GROUPS for page in pages)
        self.assertEqual(set(NAVIGATION_ITEMS) - set(grouped_pages), {"Photo Viewer", *ADVANCED_PAGE_ITEMS})
        self.assertEqual(len(grouped_pages), len(set(grouped_pages)))

    def test_technical_pages_are_reachable_without_primary_sidebar_clutter(self) -> None:
        from photovault.ui import main_window

        if not main_window.QT_AVAILABLE:
            self.skipTest("PySide6 is not installed")
        from PySide6.QtWidgets import QApplication

        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "catalog.db")
            app = QApplication.instance() or QApplication([])
            window = main_window.MainWindow(connection)
            visible_labels = [window.navigation.item(row).text() for row in window._navigation_page_rows]
            self.assertNotIn("Scan", visible_labels)
            self.assertNotIn("Redundancy Audit", visible_labels)
            window._select_page("Scan")
            self.assertEqual(window.pages.currentIndex(), NAVIGATION_ITEMS.index("Scan"))
            window.close()
            connection.close()

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
            self.assertFalse(window.android_transfer_group.isVisible())
            self.assertFalse(window.android_profile_history_label.isVisible())
            window.android_backup_status.setText("Phone connected")
            self.assertEqual(window.android_backup_status.text(), "Phone connected")
            window.close()
            connection.close()

    def test_android_backup_terminal_states_have_explicit_safe_summary(self) -> None:
        from photovault.ui import main_window

        if not main_window.QT_AVAILABLE:
            self.skipTest("PySide6 is not installed")
        from PySide6.QtWidgets import QApplication

        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "catalog.db")
            app = QApplication.instance() or QApplication([])
            window = main_window.MainWindow(connection)
            window._android_transfer_completed = 3
            window._android_transfer_bytes = 3072
            window._android_transfer_completed_result({
                "imported": 3, "already_imported": 0, "planned": 3,
                "results": [], "destination_volume": "test-volume",
            })
            self.assertIn("Backup complete", window.android_backup_completion.text())
            self.assertIn("3 copied", window.android_backup_completion.text())
            window._android_transfer_cancelled("user requested")
            self.assertIn("cancelled safely", window.android_backup_completion.text())
            window._android_transfer_failed("destination unavailable")
            self.assertIn("completed with issues", window.android_backup_completion.text())
            window.close()
            connection.close()

    def test_gui_navigates_all_user_facing_pages_with_empty_catalog(self) -> None:
        from photovault.ui import main_window

        if not main_window.QT_AVAILABLE:
            self.skipTest("PySide6 is not installed")
        from PySide6.QtWidgets import QApplication

        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "catalog.db")
            app = QApplication.instance() or QApplication([])
            window = main_window.MainWindow(connection)
            for page in ("Dashboard", "Library", "Photo Viewer", "Collections", "People", "Places", "Categories", "Visual Duplicates", "Android Devices", "Backup Profiles", "Backup Health", "Operations", "Settings", "Advanced Tools"):
                window._select_page(page)
                self.assertEqual(window.pages.currentIndex(), NAVIGATION_ITEMS.index(page))
            self.assertIn("No photos indexed yet", [window.dashboard_recent_grid.item(i).text() for i in range(window.dashboard_recent_grid.count())])
            self.assertFalse(window._tables["Dashboard"].isVisible())
            self.assertIn("No Android backup profiles yet", window.backup_profiles_result.text())
            self.assertIn("No backup profiles", window.backup_health_result.text())
            self.assertIn("No people groups yet", [window.people_grid.item(i).text() for i in range(window.people_grid.count())])
            self.assertIn("No embedded GPS clusters yet", [window.places_grid.item(i).text() for i in range(window.places_grid.count())])
            self.assertIn("No categories indexed yet", [window.category_grid.item(i).text() for i in range(window.category_grid.count())])
            self.assertIn("No smart collections yet", [window.collections_grid.item(i).text() for i in range(window.collections_grid.count())])
            self.assertIn("No registered drives yet", [window.disks_grid.item(i).text() for i in range(window.disks_grid.count())])
            self.assertIn("No activity recorded yet", [window.activity_feed.item(i).text() for i in range(window.activity_feed.count())])
            window.close()
            connection.close()

    def test_collections_double_click_opens_library_for_empty_album(self) -> None:
        from photovault.ui import main_window

        if not main_window.QT_AVAILABLE:
            self.skipTest("PySide6 is not installed")
        from PySide6.QtWidgets import QApplication

        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "catalog.db")
            app = QApplication.instance() or QApplication([])
            window = main_window.MainWindow(connection)
            window.new_collection_title.setText("Empty test album")
            window._create_user_collection()
            table = window._tables["Collections"]
            self.assertEqual(table.rowCount(), 1)
            window._open_collection_row(0, 0)
            self.assertEqual(window.pages.currentIndex(), NAVIGATION_ITEMS.index("Library"))
            self.assertIn("empty", window.library_result.text().lower())
            window.close()
            connection.close()

    def test_collections_album_tile_activation_opens_library(self) -> None:
        from photovault.ui import main_window

        if not main_window.QT_AVAILABLE:
            self.skipTest("PySide6 is not installed")
        from PySide6.QtWidgets import QApplication

        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "catalog.db")
            app = QApplication.instance() or QApplication([])
            window = main_window.MainWindow(connection)
            window.new_collection_title.setText("Tile album")
            window._create_user_collection()
            self.assertEqual(window.collections_album_grid.count(), 1)
            tile = window.collections_album_grid.item(0)
            self.assertTrue(tile.data(main_window.Qt.ItemDataRole.UserRole))
            window.collections_album_grid.itemDoubleClicked.emit(tile)
            self.assertEqual(window.pages.currentIndex(), NAVIGATION_ITEMS.index("Library"))
            self.assertIn("empty", window.library_result.text().lower())
            window.close()
            connection.close()

    def test_collections_empty_state_explains_no_action(self) -> None:
        from photovault.ui import main_window

        if not main_window.QT_AVAILABLE:
            self.skipTest("PySide6 is not installed")
        from PySide6.QtWidgets import QApplication

        with tempfile.TemporaryDirectory() as temp:
            connection = connect(Path(temp) / "catalog.db")
            app = QApplication.instance() or QApplication([])
            window = main_window.MainWindow(connection)
            window._open_collection_tile(window.collections_grid.item(0))
            self.assertIn("no smart collections", window.collections_result.text().lower())
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
