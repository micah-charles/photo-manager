from __future__ import annotations

import sqlite3
import time
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from .spec import NAVIGATION_GROUPS, NAVIGATION_ITEMS
from .theme import stylesheet

try:
    from PySide6.QtCore import QObject, QThread, QSize, Qt, Signal, Slot
    from PySide6.QtGui import QIcon, QPixmap
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QCheckBox,
        QComboBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMenu,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QStyle,
        QPushButton,
        QStackedWidget,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )

    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised by headless environments
    QT_AVAILABLE = False


def _require_qt() -> None:
    if not QT_AVAILABLE:
        raise RuntimeError("PySide6 is not installed; install PhotoVault with the 'desktop' extra to use the GUI")


if QT_AVAILABLE:

    from .components import add_tile, clear_tile_grid, configure_tile_grid

    @dataclass(frozen=True)
    class UndoQuarantineRequest:
        operation_id: str

    class ScanWorker(QObject):
        """Run a scan on a worker thread using its own SQLite connection."""

        completed = Signal(object)
        failed = Signal(str)

        def __init__(self, catalog_path: Path, volume_id: str, root: Path):
            super().__init__()
            self.catalog_path = catalog_path
            self.volume_id = volume_id
            self.root = root

        @Slot()
        def run(self) -> None:
            from photovault.catalog.scanner import scan_volume
            from photovault.database.connection import connect

            connection: sqlite3.Connection | None = None
            try:
                connection = connect(self.catalog_path)
                result = scan_volume(connection, self.volume_id, self.root)
                self.completed.emit(result)
            except Exception as exc:  # deliver a readable error to the GUI thread
                self.failed.emit(f"{type(exc).__name__}: {exc}")
            finally:
                if connection is not None:
                    connection.close()

    class AndroidDiscoveryWorker(QObject):
        """Discover Android source metadata away from the PySide6 UI thread."""

        completed = Signal(object)
        failed = Signal(str)

        def __init__(self, helper: Path):
            super().__init__()
            self.helper = helper

        @Slot()
        def run(self) -> None:
            source = None
            try:
                from photovault.sources.android import AndroidMacMtpSource

                source = AndroidMacMtpSource.from_helper(self.helper)
                self.completed.emit({
                    "identity": source.identity(),
                    "storages": list(source.list_storages()),
                })
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")
            finally:
                if source is not None:
                    source.close()

    class AndroidCompanionDiscoveryWorker(QObject):
        """Fetch a Companion Wi-Fi manifest away from the PySide6 UI thread."""

        completed = Signal(object)
        failed = Signal(str)

        def __init__(self, url: str, token: str):
            super().__init__()
            self.url = url
            self.token = token

        @Slot()
        def run(self) -> None:
            try:
                from photovault.sources.android_wifi import AndroidCompanionWifiSource

                source = AndroidCompanionWifiSource(self.url, self.token)
                self.completed.emit({
                    "identity": source.identity(),
                    "device": source.device_details(),
                    "folders": source.folders(),
                })
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")

    class AndroidCompanionTransferWorker(QObject):
        """Plan and execute a verified, read-only Companion import off the UI thread."""

        progress = Signal(object)
        completed = Signal(object)
        cancelled = Signal(str)
        failed = Signal(str)

        def __init__(self, catalog_path: Path, url: str, token: str, profile_name: str, folders: tuple[str, ...], media_filter: str, destination: Path, workers: int):
            super().__init__()
            self.catalog_path = catalog_path
            self.url = url
            self.token = token
            self.profile_name = profile_name
            self.folders = folders
            self.media_filter = media_filter
            self.destination = destination
            self.workers = workers
            self._cancel = Event()

        def request_cancel(self) -> None:
            self._cancel.set()

        @Slot()
        def run(self) -> None:
            from photovault.backup.source_import import ImportCancelled, SourceImportItem, import_source_items, plan_source_import
            from photovault.backup.android_profiles import finish_android_backup_snapshot, missing_from_source, start_android_backup_snapshot, upsert_android_backup_profile
            from photovault.catalog.scanner import register_volume
            from photovault.database.connection import connect
            from photovault.sources.android_wifi import AndroidCompanionWifiSource

            connection: sqlite3.Connection | None = None
            snapshot_id: str | None = None
            imported_items = 0
            imported_bytes = 0
            try:
                self.progress.emit({"stage": "inventory"})
                source = AndroidCompanionWifiSource(self.url, self.token)
                items = []
                import_items = []
                for folder in self.folders:
                    folder_items = [
                        item for item in source.iter_folder(folder)
                        if self.media_filter == "ALL" or item.media_type == self.media_filter
                    ]
                    items.extend(folder_items)
                    import_items.extend(SourceImportItem(
                        item.object_id, f"{folder.strip('/')}/{item.name}", item.size_bytes,
                        media_type=item.media_type, modified_at=item.modified_at,
                    ) for item in folder_items)
                if len({item.relative_path for item in import_items}) != len(import_items):
                    raise ValueError("selected folder contains duplicate destination names; nothing was copied")
                if self._cancel.is_set():
                    raise ImportCancelled("import cancelled before transfer")
                connection = connect(self.catalog_path)
                destination_volume = register_volume(connection, self.destination)
                decisions = plan_source_import(connection, source, import_items, self.destination, destination_volume)
                conflicts = sum(1 for decision in decisions if decision.status.value == "CONFLICT")
                new_items = sum(1 for decision in decisions if decision.status.value == "NEW")
                unchanged_items = sum(1 for decision in decisions if decision.status.value == "ALREADY_IMPORTED")
                missing_items = missing_from_source(
                    connection, source_id=source.identity().source_id, destination_volume_id=destination_volume,
                    folders=self.folders, current_logical_paths=(item.relative_path for item in import_items),
                )
                bytes_total = sum(item.size_bytes or 0 for item in items)
                self.progress.emit({
                    "stage": "planned", "items": len(items), "bytes_total": bytes_total,
                    "conflicts": conflicts, "new": new_items, "unchanged": unchanged_items,
                    "missing": len(missing_items), "destination_volume": destination_volume,
                })
                profile_id = upsert_android_backup_profile(
                    connection, source_id=source.identity().source_id,
                    name=self.profile_name, folder_paths=self.folders, media_filter=self.media_filter,
                    destination_volume_id=destination_volume, workers=self.workers,
                )
                snapshot_id = start_android_backup_snapshot(
                    connection, profile_id, planned_items=len(items), planned_bytes=bytes_total,
                )
                if conflicts:
                    raise FileExistsError(f"{conflicts} destination conflict(s); nothing was copied")

                def progress(row: dict[str, object]) -> None:
                    nonlocal imported_items, imported_bytes
                    imported_items += 1
                    imported_bytes += int(row["bytes_written"])
                    self.progress.emit({"stage": "file", "row": row})

                result = import_source_items(
                    connection, source, import_items, self.destination, destination_volume,
                    progress_callback=progress,
                    retry_callback=lambda item, attempt, exc: self.progress.emit({
                        "stage": "retry", "item": item, "attempt": attempt, "error": str(exc),
                    }),
                    fsync_mode="batch", batch_files=25, workers=self.workers,
                    cancel_callback=self._cancel.is_set,
                    retry_attempts=2, retry_base_delay_seconds=0.25,
                )
                finish_android_backup_snapshot(
                    connection, snapshot_id, status="COMPLETED", imported_items=imported_items,
                    already_imported_items=int(result["already_imported"]), imported_bytes=imported_bytes,
                    details={"folders": list(self.folders), "missing_from_source": len(missing_items)},
                )
                self.completed.emit({**result, "items": len(items), "bytes_total": bytes_total,
                                     "destination_volume": destination_volume, "profile_id": profile_id,
                                     "snapshot_id": snapshot_id})
            except ImportCancelled as exc:
                if connection is not None and snapshot_id is not None:
                    finish_android_backup_snapshot(connection, snapshot_id, status="CANCELLED", imported_items=imported_items, imported_bytes=imported_bytes)
                self.cancelled.emit(str(exc))
            except Exception as exc:
                if connection is not None and snapshot_id is not None:
                    finish_android_backup_snapshot(connection, snapshot_id, status="FAILED", imported_items=imported_items, imported_bytes=imported_bytes, failed_items=1, details={"error": str(exc)})
                self.failed.emit(f"{type(exc).__name__}: {exc}")
            finally:
                if connection is not None:
                    connection.close()

    class ClassificationWorker(QObject):
        """Run optional local image enrichment without blocking the desktop UI."""

        progress = Signal(object)
        completed = Signal(object)
        cancelled = Signal(str)
        failed = Signal(str)

        def __init__(self, catalog_path: Path, model_path: Path, labels_path: Path, limit: int, top_k: int):
            super().__init__()
            self.catalog_path = catalog_path
            self.model_path = model_path
            self.labels_path = labels_path
            self.limit = limit
            self.top_k = top_k
            self._cancel = Event()

        def request_cancel(self) -> None:
            self._cancel.set()

        @Slot()
        def run(self) -> None:
            from photovault.catalog.classification import ClassificationCancelled, OnnxImageNetClassifier, index_image_categories
            from photovault.database.connection import connect

            connection: sqlite3.Connection | None = None
            try:
                connection = connect(self.catalog_path)
                classifier = OnnxImageNetClassifier(self.model_path, self.labels_path)
                result = index_image_categories(
                    connection, classifier, limit=self.limit, top_k=self.top_k,
                    progress_callback=self.progress.emit, cancel_callback=self._cancel.is_set,
                )
                self.completed.emit(result)
            except ClassificationCancelled as exc:
                self.cancelled.emit(str(exc))
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")
            finally:
                if connection is not None:
                    connection.close()

    class ThumbnailWorker(QObject):
        """Build rebuildable catalog thumbnails without blocking the UI."""

        progress = Signal(object)
        completed = Signal(object)
        failed = Signal(str)

        def __init__(self, catalog_path: Path, limit: int = 200):
            super().__init__()
            self.catalog_path = catalog_path
            self.limit = limit
            self._cancel = Event()

        def request_cancel(self) -> None:
            self._cancel.set()

        @Slot()
        def run(self) -> None:
            from photovault.catalog.thumbnails import generate_thumbnail
            from photovault.database.connection import connect

            connection: sqlite3.Connection | None = None
            generated = skipped = 0
            try:
                connection = connect(self.catalog_path)
                cache_root = self.catalog_path.parent / ".photovault-thumbnails"
                rows = connection.execute(
                    """SELECT a.id, a.media_type, al.relative_path, v.current_mount_path
                       FROM assets a JOIN asset_locations al ON al.asset_id=a.id
                       JOIN volumes v ON v.id=al.volume_id
                       LEFT JOIN media_metadata mm ON mm.asset_id=a.id
                       LEFT JOIN thumbnails t ON t.asset_id=a.id AND t.version='v1-320'
                       WHERE al.missing_since IS NULL AND t.asset_id IS NULL
                       ORDER BY (COALESCE(mm.capture_datetime, al.capture_date,
                                          datetime(al.modified_ns / 1000000000, 'unixepoch')) IS NULL),
                                COALESCE(mm.capture_datetime, al.capture_date,
                                         datetime(al.modified_ns / 1000000000, 'unixepoch')) DESC,
                                al.relative_path
                       LIMIT ?""", (self.limit,)
                ).fetchall()
                total = len(rows)
                for index, row in enumerate(rows, 1):
                    if self._cancel.is_set():
                        break
                    source = Path(str(row[3])) / str(row[2])
                    if str(row[1]) == "IMAGE" and source.is_file():
                        if generate_thumbnail(connection, str(row[0]), source, cache_root) is not None:
                            generated += 1
                        else:
                            skipped += 1
                    else:
                        skipped += 1
                    if index % 25 == 0:
                        connection.commit()
                    self.progress.emit({"processed": index, "total": total, "generated": generated, "skipped": skipped})
                connection.commit()
                self.completed.emit({"processed": generated + skipped, "total": total, "generated": generated, "skipped": skipped, "cancelled": self._cancel.is_set()})
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")
            finally:
                if connection is not None:
                    connection.close()

    class CatalogRecoveryWorker(QObject):
        """Run catalog backup/integrity work without blocking the desktop UI."""

        completed = Signal(object)
        failed = Signal(str)

        def __init__(self, catalog_path: Path, *, destination: Path | None = None):
            super().__init__()
            self.catalog_path = catalog_path
            self.destination = destination

        @Slot()
        def run(self) -> None:
            try:
                from photovault.catalog.recovery import backup_catalog, check_catalog_integrity

                if self.destination is None:
                    self.completed.emit({"kind": "check", "integrity": check_catalog_integrity(self.catalog_path)})
                else:
                    result = backup_catalog(self.catalog_path, self.destination)
                    self.completed.emit({
                        "kind": "backup", "destination": str(result.destination),
                        "bytes_written": result.bytes_written, "integrity": result.integrity,
                    })
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")

    class OperationWorker(QObject):
        """Execute an already reviewed copy/quarantine plan off the GUI thread."""

        completed = Signal(object)
        failed = Signal(str)

        def __init__(self, catalog_path: Path, plan: object):
            super().__init__()
            self.catalog_path = catalog_path
            self.plan = plan

        @Slot()
        def run(self) -> None:
            from photovault.backup.copy import CopyPlan, execute_copy_plan
            from photovault.backup.quarantine import QuarantinePlan, execute_quarantine_plan, undo_quarantine
            from photovault.database.connection import connect

            connection: sqlite3.Connection | None = None
            try:
                connection = connect(self.catalog_path)
                if isinstance(self.plan, CopyPlan):
                    result = execute_copy_plan(connection, self.plan)
                elif isinstance(self.plan, QuarantinePlan):
                    result = execute_quarantine_plan(connection, self.plan)
                elif isinstance(self.plan, UndoQuarantineRequest):
                    result = undo_quarantine(connection, self.plan.operation_id)
                else:
                    raise TypeError("unsupported operation plan")
                self.completed.emit(result)
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")
            finally:
                if connection is not None:
                    connection.close()

    class MainWindow(QMainWindow):
        def __init__(self, connection: sqlite3.Connection):
            super().__init__()
            self.connection = connection
            self.setWindowTitle(os.environ.get("PHOTOVAULT_WINDOW_TITLE", "PhotoVault"))
            self.resize(1180, 760)
            self._tables: dict[str, QTableWidget] = {}
            self._inputs: dict[str, QLineEdit] = {}
            self._results: dict[str, QLabel] = {}
            database_row = connection.execute("PRAGMA database_list").fetchone()
            database_path = database_row[2] if database_row else ""
            self._catalog_path = Path(database_path) if database_path else None
            self._scan_thread: QThread | None = None
            self._scan_worker: ScanWorker | None = None
            self._android_thread: QThread | None = None
            self._android_worker: AndroidDiscoveryWorker | None = None
            self._android_companion_thread: QThread | None = None
            self._android_companion_worker: AndroidCompanionDiscoveryWorker | None = None
            self._android_transfer_thread: QThread | None = None
            self._android_transfer_worker: AndroidCompanionTransferWorker | None = None
            self._classification_thread: QThread | None = None
            self._classification_worker: ClassificationWorker | None = None
            self._thumbnail_thread: QThread | None = None
            self._thumbnail_worker: ThumbnailWorker | None = None
            self._catalog_recovery_thread: QThread | None = None
            self._catalog_recovery_worker: CatalogRecoveryWorker | None = None
            self._android_transfer_completed = 0
            self._android_transfer_bytes = 0
            self._android_transfer_total = 0
            self._android_transfer_total_bytes = 0
            self._android_transfer_started = 0.0
            self._android_transfer_checkpoint = 0.0
            self._android_transfer_checkpoint_bytes = 0
            self._operation_thread: QThread | None = None
            self._operation_worker: OperationWorker | None = None
            self._operation_kind: str | None = None
            self._copy_plan = None
            self._quarantine_plan = None
            self._library_collection_id: str | None = None
            self._library_review_status: str = ""
            self._viewer_items: list[dict[str, object]] = []
            self._viewer_index = -1

            shell = QWidget()
            shell_layout = QHBoxLayout(shell)
            shell_layout.setContentsMargins(0, 0, 0, 0)
            self.navigation = QListWidget()
            self.navigation.setObjectName("PhotoVaultNavigation")
            self.navigation.setAccessibleName("PhotoVault page navigation")
            self._navigation_page_rows: dict[int, int] = {}
            navigation_icons = {
                "Dashboard": QStyle.StandardPixmap.SP_DirHomeIcon,
                "Library": QStyle.StandardPixmap.SP_FileDialogDetailedView,
                "Review": QStyle.StandardPixmap.SP_DialogApplyButton,
                "Events": QStyle.StandardPixmap.SP_FileDialogListView,
                "Tags": QStyle.StandardPixmap.SP_FileDialogListView,
                "Sources": QStyle.StandardPixmap.SP_ComputerIcon,
                "Collections": QStyle.StandardPixmap.SP_DirIcon,
                "Favourites": QStyle.StandardPixmap.SP_DialogYesButton,
                "People": QStyle.StandardPixmap.SP_ComputerIcon,
                "Places": QStyle.StandardPixmap.SP_DialogOpenButton,
                "Categories": QStyle.StandardPixmap.SP_FileDialogListView,
                "Visual Duplicates": QStyle.StandardPixmap.SP_FileDialogContentsView,
                "Android Devices": QStyle.StandardPixmap.SP_ComputerIcon,
                "Backup Profiles": QStyle.StandardPixmap.SP_FileIcon,
                "Disks": QStyle.StandardPixmap.SP_DriveHDIcon,
                "Backup Health": QStyle.StandardPixmap.SP_DialogApplyButton,
                "Advanced Tools": QStyle.StandardPixmap.SP_ToolBarHorizontalExtensionButton,
                "Operations": QStyle.StandardPixmap.SP_BrowserReload,
                "Settings": QStyle.StandardPixmap.SP_FileDialogDetailedView,
            }
            for group_name, page_names in NAVIGATION_GROUPS:
                heading = QListWidgetItem(group_name.upper())
                heading.setFlags(Qt.ItemFlag.NoItemFlags)
                self.navigation.addItem(heading)
                for page_name in page_names:
                    item = QListWidgetItem("Home" if page_name == "Dashboard" else page_name)
                    icon_kind = navigation_icons.get(page_name)
                    if icon_kind is not None:
                        item.setIcon(self.style().standardIcon(icon_kind))
                    row = self.navigation.count()
                    self._navigation_page_rows[row] = NAVIGATION_ITEMS.index(page_name)
                    self.navigation.addItem(item)
            self.navigation.setFixedWidth(220)
            self.navigation.currentRowChanged.connect(self._show_navigation_row)
            shell_layout.addWidget(self.navigation)

            self.pages = QStackedWidget()
            for label in NAVIGATION_ITEMS:
                self.pages.addWidget(self._build_page(label))
            shell_layout.addWidget(self.pages, 1)
            self.setCentralWidget(shell)
            self.navigation.setCurrentRow(next(iter(self._navigation_page_rows)))
            self.refresh()

        def _build_page(self, label: str) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            title = QLabel(label)
            title.setObjectName("PageTitle")
            layout.addWidget(title)
            if label == "Dashboard":
                from .pages.home_page import build_home_page

                build_home_page(self, layout, self._tables)
            elif label == "Android Devices":
                from .pages.android_backup_page import build_android_backup_page

                build_android_backup_page(self, layout, self._tables)
            elif label == "Backup Profiles":
                from .pages.backup_profiles_page import build_backup_profiles_page

                build_backup_profiles_page(self, layout, self._tables)
            elif label == "Scan":
                from .pages.technical_pages import build_scan_page

                build_scan_page(self, layout)
            elif label == "Backup Health":
                from .pages.backup_health_page import build_backup_health_page

                build_backup_health_page(self, layout, self._tables)
            elif label in {"Redundancy Audit", "Reconciliation"}:
                from .pages.technical_pages import build_set_report_page

                build_set_report_page(self, layout, label)
            elif label == "Folder Safety Audit":
                from .pages.technical_pages import build_folder_safety_page

                build_folder_safety_page(self, layout)
            elif label == "Copy Plans":
                form = QFormLayout()
                self.copy_set_id = QLineEdit()
                self.copy_backup_volume = QLineEdit()
                form.addRow("Backup set ID", self.copy_set_id)
                form.addRow("Backup volume ID (optional)", self.copy_backup_volume)
                layout.addLayout(form)
                button = QPushButton("Build dry-run copy plan")
                button.clicked.connect(self._build_copy_plan)
                layout.addWidget(button)
                self.copy_execute_button = QPushButton("Execute reviewed copy plan")
                self.copy_execute_button.setEnabled(False)
                self.copy_execute_button.clicked.connect(self._execute_copy_plan)
                layout.addWidget(self.copy_execute_button)
                self.copy_result = QLabel("A dry-run plan changes catalog journal only; it does not copy files.")
                self.copy_result.setWordWrap(True)
                layout.addWidget(self.copy_result)
                table = QTableWidget()
                self._tables[label] = table
                layout.addWidget(table)
            elif label == "Quarantine":
                form = QFormLayout()
                self.quarantine_paths = QPlainTextEdit()
                self.quarantine_paths.setPlaceholderText("One catalogued file path per line")
                self.quarantine_reason = QLineEdit("user-requested quarantine")
                form.addRow("Files", self.quarantine_paths)
                form.addRow("Reason", self.quarantine_reason)
                layout.addLayout(form)
                button = QPushButton("Build reversible quarantine plan")
                button.clicked.connect(self._build_quarantine_plan)
                layout.addWidget(button)
                self.quarantine_execute_button = QPushButton("Execute reviewed quarantine")
                self.quarantine_execute_button.setEnabled(False)
                self.quarantine_execute_button.clicked.connect(self._execute_quarantine_plan)
                layout.addWidget(self.quarantine_execute_button)
                self.quarantine_result = QLabel("Planning only: no file is moved by this button. Review and execute via the CLI.")
                self.quarantine_result.setWordWrap(True)
                layout.addWidget(self.quarantine_result)
            elif label == "Library":
                from .pages.library_page import build_library_page

                build_library_page(self, layout, self._tables)
            elif label == "Review":
                from .pages.review_page import build_review_page

                build_review_page(self, layout)
            elif label == "Events":
                from .pages.events_page import build_events_page

                build_events_page(self, layout, self._tables)
            elif label == "Tags":
                from .pages.tags_page import build_tags_page

                build_tags_page(self, layout, self._tables)
            elif label == "Sources":
                from .pages.sources_page import build_sources_page

                build_sources_page(self, layout, self._tables)
            elif label == "Collections":
                from .pages.collections_page import build_collections_page

                build_collections_page(self, layout, self._tables)
            elif label == "Photo Viewer":
                from .pages.photo_viewer_page import build_photo_viewer_page

                build_photo_viewer_page(self, layout)
            elif label == "People":
                from .pages.people_page import build_people_page

                build_people_page(self, layout, self._tables)
            elif label == "Categories":
                from .pages.categories_page import build_categories_page

                build_categories_page(self, layout, self._tables)
            elif label == "Timeline":
                from .pages.timeline_page import build_timeline_page

                build_timeline_page(self, layout, self._tables)
            elif label == "Visual Duplicates":
                from .pages.duplicates_page import build_duplicates_page

                build_duplicates_page(self, layout)
            elif label == "Places":
                from .pages.places_page import build_places_page

                build_places_page(self, layout, self._tables)
            elif label == "Favourites":
                from .pages.favourites_page import build_favourites_page

                build_favourites_page(self, layout, self._tables)
            elif label == "Disks":
                from .pages.disks_page import build_disks_page

                build_disks_page(self, layout, self._tables)
            elif label == "Backup Sets":
                from .pages.backup_sets_page import build_backup_sets_page

                build_backup_sets_page(self, layout, self._tables)
            elif label == "Operations":
                from .pages.activity_page import build_activity_page

                build_activity_page(self, layout, self._tables)
            elif label == "Catalog Recovery":
                form = QFormLayout()
                self.catalog_backup_destination = QLineEdit()
                self.catalog_backup_destination.setPlaceholderText("New .db file on a selected external destination")
                form.addRow("New catalog backup file", self.catalog_backup_destination)
                layout.addLayout(form)
                check_button = QPushButton("Check live catalog integrity")
                check_button.clicked.connect(self._check_catalog_integrity)
                layout.addWidget(check_button)
                backup_button = QPushButton("Create verified catalog backup")
                backup_button.clicked.connect(self._backup_catalog)
                layout.addWidget(backup_button)
                self.catalog_recovery_result = QLabel(
                    "Catalog backup uses SQLite's online backup API. It must be a new file; no existing backup or live catalog is overwritten."
                )
                self.catalog_recovery_result.setWordWrap(True)
                layout.addWidget(self.catalog_recovery_result)
            elif label in {"Settings", "Advanced Tools"}:
                if label == "Settings":
                    from .pages.settings_page import build_settings_page

                    build_settings_page(self, layout)
                else:
                    from .pages.advanced_tools_page import build_advanced_tools_page

                    build_advanced_tools_page(self, layout)
            else:
                hint = QLabel(self._page_hint(label))
                hint.setWordWrap(True)
                layout.addWidget(hint)
                refresh = QPushButton("Refresh")
                refresh.clicked.connect(self.refresh)
                layout.addWidget(refresh)
            layout.addStretch(1)
            return page

        @staticmethod
        def _page_hint(label: str) -> str:
            hints = {
                "Dashboard": "Integrity-first overview. Use Disks, Backup Sets and Operations to inspect the local catalog.",
                "Redundancy Audit": "Read-only protection report from the same core service as backup-audit.",
                "Reconciliation": "Read-only Main/Backup comparison from the same core service as reconcile.",
                "Folder Safety Audit": "Read-only redundancy check from the same core service as audit-folder; no deletion is performed.",
            }
            return hints.get(label, "")

        def _show_page(self, row: int) -> None:
            self.pages.setCurrentIndex(max(row, 0))

        def _show_navigation_row(self, row: int) -> None:
            page_index = self._navigation_page_rows.get(row)
            if page_index is not None:
                self._show_page(page_index)

        def _select_page(self, page_name: str) -> None:
            page_index = NAVIGATION_ITEMS.index(page_name)
            for row, index in self._navigation_page_rows.items():
                if index == page_index:
                    self.navigation.setCurrentRow(row)
                    return
            # Technical pages are intentionally hidden from the primary
            # sidebar. Advanced Tools opens them directly while the sidebar
            # remains available for returning to a normal user-facing page.
            self.pages.setCurrentIndex(page_index)

        def _register_disk(self) -> None:
            try:
                from photovault.catalog.scanner import register_volume

                root = Path(self.disk_root.text().strip())
                volume_id = register_volume(self.connection, root)
                self.disk_result.setText(f"Registered {volume_id}. Registration only updates the catalog; run Scan separately.")
                self.refresh()
            except Exception as exc:
                self.disk_result.setText(f"Registration failed: {type(exc).__name__}: {exc}")

        def _create_backup_set(self) -> None:
            try:
                from photovault.backup.sets import create_backup_set

                set_id = create_backup_set(
                    self.connection,
                    self.backup_set_name.text().strip(),
                    int(self.backup_set_copies.text().strip()),
                    self.backup_set_scope.text().strip(),
                )
                self.backup_set_result.setText(f"Created {set_id}. Add a PRIMARY and BACKUP volume member below.")
                self.member_set_id.setText(set_id)
                self.refresh()
            except Exception as exc:
                self.backup_set_result.setText(f"Create failed: {type(exc).__name__}: {exc}")

        def _add_backup_member(self) -> None:
            try:
                from photovault.backup.sets import add_member

                add_member(
                    self.connection,
                    self.member_set_id.text().strip(),
                    self.member_volume_id.text().strip(),
                    self.member_role.text().strip(),
                    self.member_relative_root.text().strip(),
                )
                self.backup_set_result.setText("Backup-set member added. Run a redundancy audit before taking action.")
                self.refresh()
            except Exception as exc:
                self.backup_set_result.setText(f"Add member failed: {type(exc).__name__}: {exc}")

        def _scan(self) -> None:
            if self._scan_thread is not None and self._scan_thread.isRunning():
                return
            volume_id = self.scan_volume_id.text().strip()
            root = Path(self.scan_root.text().strip())
            if self._catalog_path is None:
                # In-memory connections are useful in tests; retain a safe synchronous fallback.
                from photovault.catalog.scanner import scan_volume

                try:
                    result = scan_volume(self.connection, volume_id, root)
                    self.scan_result.setText(f"Completed: {result['files_catalogued']} files, {result['errors']} errors")
                    self.refresh()
                except Exception as exc:
                    self.scan_result.setText(f"Scan failed: {exc}")
                return
            self.scan_button.setEnabled(False)
            self.scan_result.setText("Scanning in background…")
            self._scan_thread = QThread(self)
            self._scan_worker = ScanWorker(self._catalog_path, volume_id, root)
            self._scan_worker.moveToThread(self._scan_thread)
            self._scan_thread.started.connect(self._scan_worker.run)
            self._scan_worker.completed.connect(self._scan_completed)
            self._scan_worker.failed.connect(self._scan_failed)
            self._scan_worker.completed.connect(self._scan_thread.quit)
            self._scan_worker.failed.connect(self._scan_thread.quit)
            self._scan_worker.completed.connect(self._scan_worker.deleteLater)
            self._scan_worker.failed.connect(self._scan_worker.deleteLater)
            self._scan_thread.finished.connect(self._scan_thread_finished)
            self._scan_thread.finished.connect(self._scan_thread.deleteLater)
            self._scan_thread.start()

        def _discover_android(self) -> None:
            if self._android_thread is not None and self._android_thread.isRunning():
                return
            self.android_discover_button.setEnabled(False)
            self.android_result.setText("Discovering Android source in background…")
            self._android_thread = QThread(self)
            self._android_worker = AndroidDiscoveryWorker(Path(self.android_helper.text().strip()))
            self._android_worker.moveToThread(self._android_thread)
            self._android_thread.started.connect(self._android_worker.run)
            self._android_worker.completed.connect(self._android_completed)
            self._android_worker.failed.connect(self._android_failed)
            self._android_worker.completed.connect(self._android_thread.quit)
            self._android_worker.failed.connect(self._android_thread.quit)
            self._android_worker.completed.connect(self._android_worker.deleteLater)
            self._android_worker.failed.connect(self._android_worker.deleteLater)
            self._android_thread.finished.connect(self._android_thread_finished)
            self._android_thread.finished.connect(self._android_thread.deleteLater)
            self._android_thread.start()

        def _discover_android_companion(self) -> None:
            if self._android_companion_thread is not None and self._android_companion_thread.isRunning():
                return
            url = self.android_companion_url.text().strip()
            token = self.android_companion_token.text().strip()
            if not url or url == "http://" or not token:
                self.android_result.setText("Enter the Companion URL and token shown on the Android phone.")
                return
            self.android_companion_discover_button.setEnabled(False)
            self.android_result.setText("Connecting to Android Companion in background…")
            self._android_companion_thread = QThread(self)
            self._android_companion_worker = AndroidCompanionDiscoveryWorker(url, token)
            self._android_companion_worker.moveToThread(self._android_companion_thread)
            self._android_companion_thread.started.connect(self._android_companion_worker.run)
            self._android_companion_worker.completed.connect(self._android_companion_completed)
            self._android_companion_worker.failed.connect(self._android_companion_failed)
            self._android_companion_worker.completed.connect(self._android_companion_thread.quit)
            self._android_companion_worker.failed.connect(self._android_companion_thread.quit)
            self._android_companion_worker.completed.connect(self._android_companion_worker.deleteLater)
            self._android_companion_worker.failed.connect(self._android_companion_worker.deleteLater)
            self._android_companion_thread.finished.connect(self._android_companion_thread_finished)
            self._android_companion_thread.finished.connect(self._android_companion_thread.deleteLater)
            self._android_companion_thread.start()

        def _start_android_companion_transfer(self) -> None:
            if self._android_transfer_thread is not None and self._android_transfer_thread.isRunning():
                return
            if self._catalog_path is None:
                self.android_transfer_result.setText("A file-backed catalog is required before starting a backup.")
                return
            url = self.android_companion_url.text().strip()
            token = self.android_companion_token.text().strip()
            folders = tuple(dict.fromkeys(
                line.strip().strip("/")
                for line in self.android_transfer_folders.toPlainText().splitlines()
                if line.strip().strip("/")
            ))
            profile_name = self.android_transfer_profile_name.text().strip()
            media_filter = str(self.android_transfer_media_filter.currentData())
            destination_text = self.android_transfer_destination.text().strip()
            if not url or url == "http://" or not token or not folders or not profile_name or not destination_text:
                self.android_transfer_result.setText("Enter Companion URL, token, at least one folder and an existing destination directory.")
                return
            destination = Path(destination_text).expanduser()
            if not destination.is_dir():
                self.android_transfer_result.setText("Destination must be an existing directory.")
                return
            try:
                workers = int(self.android_transfer_workers.text().strip())
                if not 1 <= workers <= 8:
                    raise ValueError
            except ValueError:
                self.android_transfer_result.setText("Workers must be a whole number from 1 to 8.")
                return
            self._android_transfer_completed = 0
            self._android_transfer_bytes = 0
            self._android_transfer_total = 0
            self._android_transfer_total_bytes = 0
            self._android_transfer_started = time.monotonic()
            self._android_transfer_checkpoint = self._android_transfer_started
            self._android_transfer_checkpoint_bytes = 0
            self.android_transfer_button.setEnabled(False)
            self.android_transfer_cancel_button.setEnabled(True)
            self.android_backup_status.setText("Backup in progress")
            self.android_device_card.setText("Android Companion\nConnected · backup is running in the background")
            self.android_backup_summary.setText("Building the phone inventory, then copying and verifying files in the background…")
            self.android_backup_progress.setValue(0)
            self.android_backup_progress.setFormat("Preparing…")
            self.android_transfer_result.setText("Building a read-only source inventory in background…")
            self._android_transfer_thread = QThread(self)
            self._android_transfer_worker = AndroidCompanionTransferWorker(
                self._catalog_path, url, token, profile_name, folders, media_filter, destination, workers,
            )
            self._android_transfer_worker.moveToThread(self._android_transfer_thread)
            self._android_transfer_thread.started.connect(self._android_transfer_worker.run)
            self._android_transfer_worker.progress.connect(self._android_transfer_progress)
            self._android_transfer_worker.completed.connect(self._android_transfer_completed_result)
            self._android_transfer_worker.cancelled.connect(self._android_transfer_cancelled)
            self._android_transfer_worker.failed.connect(self._android_transfer_failed)
            self._android_transfer_worker.completed.connect(self._android_transfer_thread.quit)
            self._android_transfer_worker.cancelled.connect(self._android_transfer_thread.quit)
            self._android_transfer_worker.failed.connect(self._android_transfer_thread.quit)
            self._android_transfer_worker.completed.connect(self._android_transfer_worker.deleteLater)
            self._android_transfer_worker.cancelled.connect(self._android_transfer_worker.deleteLater)
            self._android_transfer_worker.failed.connect(self._android_transfer_worker.deleteLater)
            self._android_transfer_thread.finished.connect(self._android_transfer_thread_finished)
            self._android_transfer_thread.finished.connect(self._android_transfer_thread.deleteLater)
            self._android_transfer_thread.start()

        def _start_thumbnail_generation(self) -> None:
            if self._catalog_path is None:
                self.library_thumbnail_status.setText("Thumbnail generation requires a file-backed catalog.")
                if hasattr(self, "dashboard_thumbnail_status"):
                    self.dashboard_thumbnail_status.setText("Preview generation requires a file-backed catalog.")
                return
            if self._thumbnail_thread is not None and self._thumbnail_thread.isRunning():
                self.library_thumbnail_status.setText("Thumbnail generation is already running in the background.")
                if hasattr(self, "dashboard_thumbnail_status"):
                    self.dashboard_thumbnail_status.setText("Preview generation is already running in the background.")
                return
            self.library_thumbnail_button.setEnabled(False)
            if hasattr(self, "dashboard_thumbnail_button"):
                self.dashboard_thumbnail_button.setEnabled(False)
            self.library_thumbnail_cancel_button.setEnabled(True)
            self.library_thumbnail_status.setText("Building missing thumbnails in the background; originals remain read-only…")
            if hasattr(self, "dashboard_thumbnail_status"):
                self.dashboard_thumbnail_status.setText("Building missing previews in the background; originals remain read-only…")
            self._thumbnail_thread = QThread(self)
            self._thumbnail_worker = ThumbnailWorker(self._catalog_path, limit=200)
            self._thumbnail_worker.moveToThread(self._thumbnail_thread)
            self._thumbnail_thread.started.connect(self._thumbnail_worker.run)
            self._thumbnail_worker.progress.connect(self._thumbnail_progress)
            self._thumbnail_worker.completed.connect(self._thumbnail_completed)
            self._thumbnail_worker.failed.connect(self._thumbnail_failed)
            self._thumbnail_worker.completed.connect(self._thumbnail_thread.quit)
            self._thumbnail_worker.failed.connect(self._thumbnail_thread.quit)
            self._thumbnail_worker.completed.connect(self._thumbnail_worker.deleteLater)
            self._thumbnail_worker.failed.connect(self._thumbnail_worker.deleteLater)
            self._thumbnail_thread.finished.connect(self._thumbnail_thread_finished)
            self._thumbnail_thread.finished.connect(self._thumbnail_thread.deleteLater)
            self._thumbnail_thread.start()

        def _cancel_thumbnail_generation(self) -> None:
            if self._thumbnail_worker is not None:
                self.library_thumbnail_status.setText("Stopping thumbnail build safely after the current preview…")
                if hasattr(self, "dashboard_thumbnail_status"):
                    self.dashboard_thumbnail_status.setText("Stopping preview build safely after the current preview…")
                self._thumbnail_worker.request_cancel()

        def _thumbnail_progress(self, event: object) -> None:
            self.library_thumbnail_status.setText(
                f"Building thumbnails… {event['processed']}/{event['total']} processed; "
                f"{event['generated']} generated, {event['skipped']} skipped."
            )
            if hasattr(self, "dashboard_thumbnail_status"):
                self.dashboard_thumbnail_status.setText(
                    f"Building previews… {event['processed']}/{event['total']} processed; "
                    f"{event['generated']} generated, {event['skipped']} skipped."
                )

        def _thumbnail_completed(self, result: object) -> None:
            state = "cancelled" if result["cancelled"] else "complete"
            self.library_thumbnail_status.setText(
                f"Thumbnail build {state}: {result['generated']} generated, {result['skipped']} skipped. "
                "Previews are rebuildable catalog data; originals were not changed."
            )
            if hasattr(self, "dashboard_thumbnail_status"):
                self.dashboard_thumbnail_status.setText(
                    f"Preview build {state}: {result['generated']} generated, {result['skipped']} skipped. "
                    "Originals were not changed."
                )
            self._refresh_library()
            self._refresh_dashboard()

        def _thumbnail_failed(self, message: str) -> None:
            self.library_thumbnail_status.setText(f"Thumbnail build failed safely: {message}")
            if hasattr(self, "dashboard_thumbnail_status"):
                self.dashboard_thumbnail_status.setText(f"Preview build failed safely: {message}")

        def _thumbnail_thread_finished(self) -> None:
            self.library_thumbnail_button.setEnabled(True)
            if hasattr(self, "dashboard_thumbnail_button"):
                self.dashboard_thumbnail_button.setEnabled(True)
            self.library_thumbnail_cancel_button.setEnabled(False)
            self._thumbnail_worker = None
            self._thumbnail_thread = None

        def _cancel_android_companion_transfer(self) -> None:
            if self._android_transfer_worker is not None:
                self._android_transfer_worker.request_cancel()
                self.android_transfer_cancel_button.setEnabled(False)
                self.android_transfer_result.setText("Cancellation requested; active network chunks will stop safely.")

        def _start_catalog_recovery(self, destination: Path | None) -> None:
            if self._catalog_path is None:
                self.catalog_recovery_result.setText("A file-backed catalog is required for recovery actions.")
                return
            if self._catalog_recovery_thread is not None and self._catalog_recovery_thread.isRunning():
                return
            self._catalog_recovery_thread = QThread(self)
            self._catalog_recovery_worker = CatalogRecoveryWorker(self._catalog_path, destination=destination)
            self._catalog_recovery_worker.moveToThread(self._catalog_recovery_thread)
            self._catalog_recovery_thread.started.connect(self._catalog_recovery_worker.run)
            self._catalog_recovery_worker.completed.connect(self._catalog_recovery_completed)
            self._catalog_recovery_worker.failed.connect(self._catalog_recovery_failed)
            self._catalog_recovery_worker.completed.connect(self._catalog_recovery_thread.quit)
            self._catalog_recovery_worker.failed.connect(self._catalog_recovery_thread.quit)
            self._catalog_recovery_worker.completed.connect(self._catalog_recovery_worker.deleteLater)
            self._catalog_recovery_worker.failed.connect(self._catalog_recovery_worker.deleteLater)
            self._catalog_recovery_thread.finished.connect(self._catalog_recovery_finished)
            self._catalog_recovery_thread.finished.connect(self._catalog_recovery_thread.deleteLater)
            self._catalog_recovery_thread.start()

        def _check_catalog_integrity(self) -> None:
            self.catalog_recovery_result.setText("Checking catalog integrity in background…")
            self._start_catalog_recovery(None)

        def _backup_catalog(self) -> None:
            destination_text = self.catalog_backup_destination.text().strip()
            if not destination_text:
                self.catalog_recovery_result.setText("Enter a new catalog backup filename first.")
                return
            destination = Path(destination_text).expanduser()
            self.catalog_recovery_result.setText("Creating a consistent catalog backup in background…")
            self._start_catalog_recovery(destination)

        def _catalog_recovery_completed(self, result: object) -> None:
            if result["kind"] == "check":
                self.catalog_recovery_result.setText(f"Catalog integrity: {', '.join(result['integrity'])}.")
            else:
                self.catalog_recovery_result.setText(
                    f"Verified catalog backup created: {result['destination']} "
                    f"({self._human_bytes(result['bytes_written'])}); integrity: {', '.join(result['integrity'])}."
                )

        def _catalog_recovery_failed(self, message: str) -> None:
            self.catalog_recovery_result.setText(f"Catalog recovery action failed safely: {message}")

        def _catalog_recovery_finished(self) -> None:
            self._catalog_recovery_worker = None
            self._catalog_recovery_thread = None

        def _refresh_android_backup_profiles(self) -> None:
            """Populate saved profiles/history from the catalog without touching media."""
            from photovault.backup.android_profiles import (
                list_android_backup_profiles,
                list_android_backup_snapshots,
                profile_folders,
            )

            previous_profile_id = self.android_saved_profile.currentData()
            profiles = list_android_backup_profiles(self.connection)
            self.android_saved_profile.blockSignals(True)
            self.android_saved_profile.clear()
            self.android_saved_profile.addItem("Select a saved backup profile…", None)
            for profile in profiles:
                folders = ", ".join(profile_folders(self.connection, str(profile["id"])))
                destination = profile["destination_volume_name"]
                state = profile["destination_status"]
                self.android_saved_profile.addItem(
                    f"{profile['name']} — {folders} → {destination} ({state})", profile["id"],
                )
            if previous_profile_id is not None:
                profile_index = self.android_saved_profile.findData(previous_profile_id)
                if profile_index >= 0:
                    self.android_saved_profile.setCurrentIndex(profile_index)
            self.android_saved_profile.blockSignals(False)
            snapshots = list_android_backup_snapshots(self.connection, limit=100)
            self._fill_table(
                self.android_profile_history,
                ["Profile", "Status", "Started", "Completed", "Planned", "Imported", "Already", "Failed", "Bytes"],
                [
                    (snapshot["profile_name"], snapshot["status"], snapshot["started_at"], snapshot["completed_at"] or "",
                     snapshot["planned_items"], snapshot["imported_items"], snapshot["already_imported_items"],
                     snapshot["failed_items"], self._human_bytes(snapshot["imported_bytes"]))
                    for snapshot in snapshots
                ],
            )

        def _load_selected_android_backup_profile(self) -> bool:
            """Load profile fields only; starting a backup remains an explicit next action."""
            from photovault.backup.android_profiles import get_android_backup_profile, profile_folders

            profile_id = self.android_saved_profile.currentData()
            if not profile_id:
                self.android_transfer_result.setText("Select a saved profile first.")
                return False
            try:
                profile = get_android_backup_profile(self.connection, str(profile_id))
                folders = profile_folders(self.connection, str(profile_id))
                mount_path = profile["destination_mount_path"]
                if not mount_path:
                    raise ValueError("saved destination has no current mount path")
                destination = Path(str(mount_path))
                relative_root = str(profile["destination_relative_root"] or "")
                if relative_root:
                    destination /= relative_root
                self.android_transfer_folders.setPlainText("\n".join(folders))
                self.android_transfer_profile_name.setText(str(profile["name"]))
                media_index = self.android_transfer_media_filter.findData(str(profile["media_filter"]))
                if media_index >= 0:
                    self.android_transfer_media_filter.setCurrentIndex(media_index)
                self.android_transfer_destination.setText(str(destination))
                self.android_transfer_workers.setText(str(profile["workers"]))
                if profile["destination_status"] != "CONNECTED" or not destination.is_dir():
                    self.android_transfer_result.setText(
                        f"Loaded {profile['name']}, but its destination is currently unavailable: {destination}. "
                        "Reconnect the same volume or choose the correct existing destination before continuing."
                    )
                    return False
                self.android_transfer_result.setText(
                    f"Loaded {profile['name']}: {', '.join(folders)} → {destination}. "
                    "Review the current phone inventory, then start or continue the verified backup."
                )
                return True
            except Exception as exc:
                self.android_transfer_result.setText(f"Could not load saved profile: {type(exc).__name__}: {exc}")
                return False

        def _continue_selected_android_backup_profile(self) -> None:
            if self._load_selected_android_backup_profile():
                self._start_android_companion_transfer()

        def _android_transfer_progress(self, event: object) -> None:
            stage = event.get("stage")
            if stage == "inventory":
                self.android_backup_status.setText("Reading phone inventory")
                self.android_backup_summary.setText("Listing the selected Android folders. No phone files are changed.")
                self.android_transfer_result.setText("Reading Android folder inventory…")
                self.android_backup_progress.setValue(0)
                self.android_backup_progress.setFormat("Reading inventory…")
            elif stage == "planned":
                self._android_transfer_total = int(event["items"])
                bytes_total = int(event["bytes_total"])
                self._android_transfer_total_bytes = bytes_total
                conflicts = int(event["conflicts"])
                self.android_backup_status.setText("Ready to copy")
                self.android_backup_summary.setText(
                    f"{self._android_transfer_total:,} files selected · {self._human_bytes(bytes_total)} · "
                    f"{event['new']} new, {event['unchanged']} already verified"
                )
                self.android_backup_progress.setValue(0)
                self.android_backup_progress.setFormat(f"0/{self._android_transfer_total:,} files")
                self.android_transfer_result.setText(
                    f"Plan: {self._android_transfer_total} files, {bytes_total:,} bytes, "
                    f"new={event['new']}, unchanged={event['unchanged']}, missing from source={event['missing']} (no deletions), "
                    f"{conflicts} conflicts, destination volume {event['destination_volume']}."
                )
            elif stage == "file":
                row = event["row"]
                self._android_transfer_completed += 1
                self._android_transfer_bytes += int(row["bytes_written"])
                destination = Path(str(row["destination"])).name
                now = time.monotonic()
                elapsed = now - self._android_transfer_started
                average = self._android_transfer_bytes / elapsed if elapsed else 0.0
                interval_elapsed = now - self._android_transfer_checkpoint
                interval_bytes = self._android_transfer_bytes - self._android_transfer_checkpoint_bytes
                interval = interval_bytes / interval_elapsed if interval_elapsed else 0.0
                remaining = max(0, self._android_transfer_total_bytes - self._android_transfer_bytes)
                eta = remaining / average if average else 0.0
                self.android_backup_status.setText("Copying and verifying")
                self.android_backup_summary.setText(
                    f"{self._android_transfer_completed:,}/{self._android_transfer_total:,} files · "
                    f"{self._human_bytes(self._android_transfer_bytes)} copied · "
                    f"{self._human_bytes(average)}/s average"
                )
                progress = int((self._android_transfer_bytes / self._android_transfer_total_bytes) * 100) if self._android_transfer_total_bytes else 0
                self.android_backup_progress.setValue(max(0, min(progress, 100)))
                self.android_backup_progress.setFormat(
                    f"{self._android_transfer_completed:,}/{self._android_transfer_total:,} files · {progress}%"
                )
                self._android_transfer_checkpoint = now
                self._android_transfer_checkpoint_bytes = self._android_transfer_bytes
                self.android_transfer_result.setText(
                    f"Verified {self._android_transfer_completed}/{self._android_transfer_total}: {destination} — "
                    f"{self._human_bytes(self._android_transfer_bytes)} copied; "
                    f"avg {self._human_bytes(average)}/s, last-file {self._human_bytes(interval)}/s; "
                    f"elapsed {self._human_duration(elapsed)}, ETA {self._human_duration(eta)}."
                )
            elif stage == "retry":
                item = event["item"]
                self.android_transfer_result.setText(
                    f"Temporary transfer error for {item.relative_path}; retry {event['attempt']}/2 using a safe Range resume."
                )

        def _android_transfer_completed_result(self, result: object) -> None:
            elapsed = time.monotonic() - self._android_transfer_started
            average = self._android_transfer_bytes / elapsed if elapsed else 0.0
            resumed = sum(int(row.get("resumed_bytes", 0)) for row in result["results"])
            failed = int(result.get("failed", 0))
            considered = int(result.get("imported", 0)) + int(result.get("already_imported", 0)) + failed
            terminal_label = "Backup complete ✓" if failed == 0 else "Backup completed with issues"
            self.android_backup_completion.setText(
                f"{terminal_label}\n"
                f"{considered:,} items considered · {result['imported']:,} copied · "
                f"{result['already_imported']:,} already verified · {failed:,} failed\n"
                f"{self._human_bytes(self._android_transfer_bytes)} transferred · {self._human_duration(elapsed)}\n"
                "Completed files were verified before atomic rename; failed or partial files are not reported as protected."
            )
            self.android_transfer_result.setText(
                f"Backup complete: imported {result['imported']}, already verified {result['already_imported']}, "
                f"planned {result['planned']}; {self._human_bytes(self._android_transfer_bytes)} at "
                f"{self._human_bytes(average)}/s over {self._human_duration(elapsed)}; "
                f"resumed {self._human_bytes(resumed)}. Destination volume: {result['destination_volume']}."
            )
            self.android_backup_status.setText("Backup complete")
            self.android_device_card.setText("Android Companion\nConnected · latest backup completed successfully")
            self.android_view_photos_button.setEnabled(True)
            self.android_view_details_button.setEnabled(True)
            self.android_backup_summary.setText(
                f"Imported {result['imported']:,} new files; {result['already_imported']:,} were already verified."
            )
            self.android_backup_progress.setValue(100)
            self.android_backup_progress.setFormat("Complete")
            self._refresh_android_backup_profiles()
            self.refresh()

        def _view_android_backup_photos(self) -> None:
            """Return to the photo-first library after a completed backup."""
            self._library_collection_id = None
            self.library_search.clear()
            self.library_folder.setText("DCIM/Camera")
            self._refresh_library()
            self._select_page("Library")

        def _view_android_backup_details(self) -> None:
            """Open the auditable profile/history view without starting work."""
            self._select_page("Android Devices")
            self._refresh_android_backup_profiles()
            self.android_profile_history_label.setVisible(True)
            self.android_profile_history.setVisible(True)

        def _android_transfer_cancelled(self, message: str) -> None:
            self.android_backup_status.setText("Backup cancelled")
            self.android_device_card.setText("Android Companion\nConnected · backup paused safely; resume is available")
            self.android_backup_summary.setText("Partial files are retained safely and can be resumed later.")
            self.android_backup_progress.setFormat("Cancelled — safe to resume")
            self.android_backup_completion.setText(
                "Backup cancelled safely\n"
                f"{self._android_transfer_completed:,} file(s) completed and verified; "
                "partial files are retained for a later resume."
            )
            self.android_transfer_result.setText(f"Backup cancelled safely: {message}. Retained partial files can resume.")
            self._refresh_android_backup_profiles()

        def _android_transfer_failed(self, message: str) -> None:
            self.android_backup_status.setText("Backup failed")
            self.android_device_card.setText("Android Companion\nConnected · backup needs attention")
            self.android_backup_summary.setText("The destination and source were not modified beyond verified completed files.")
            self.android_backup_progress.setFormat("Failed — review details")
            self.android_backup_completion.setText(
                "Backup completed with issues\n"
                f"{self._android_transfer_completed:,} file(s) completed and verified before the failure. "
                "Review the error and retry; the phone and verified completed files remain safe."
            )
            self.android_transfer_result.setText(f"Android backup failed: {message}")
            self._refresh_android_backup_profiles()

        def _android_completed(self, result: object) -> None:
            identity = result["identity"]
            storages = result["storages"]
            self.android_result.setText(
                f"{identity.display_name} connected via {identity.adapter}. "
                f"{len(storages)} storage(s) discovered."
            )
            self.android_backup_status.setText("USB device connected")
            self.android_device_card.setText(f"{identity.display_name}\nConnected via experimental USB MTP")
            self.android_backup_summary.setText(f"{identity.display_name} is available through the experimental USB MTP path.")
            self.android_transfer_group.setEnabled(True)
            self.android_transfer_group.setVisible(True)
            self.android_profile_history_label.setVisible(True)
            self._tables["Android Devices"].setVisible(True)
            self._fill_table(
                self._tables["Android Devices"],
                ["Storage ID", "Name", "Capacity", "Free"],
                [(storage.storage_id, storage.name, storage.capacity_bytes, storage.free_bytes) for storage in storages],
            )

        def _android_companion_completed(self, result: object) -> None:
            identity = result["identity"]
            device = result["device"]
            folders = result["folders"]
            total_folder_bytes = sum(int(folder.size_bytes) for folder in folders)
            total_folder_items = sum(int(folder.count) for folder in folders)
            self.android_result.setText(
                f"Connected to {identity.display_name} via Wi-Fi. Device ID: {identity.source_id}. "
                f"Media: {device.get('media_count', 'unknown')}. "
                f"Companion version: {device.get('app_version', 'unknown')}."
            )
            self.android_backup_status.setText("Phone connected")
            self.android_transfer_group.setEnabled(True)
            self.android_transfer_group.setVisible(True)
            self.android_profile_history_label.setVisible(True)
            self._tables["Android Devices"].setVisible(True)
            manifest_count = device.get("media_count")
            inventory_text = (
                f"{int(manifest_count):,} media items" if isinstance(manifest_count, (int, float))
                else f"{total_folder_items:,} media items"
            )
            self.android_device_card.setText(
                f"{identity.display_name}\n"
                f"● Connected via Wi-Fi Companion\n"
                f"{inventory_text} · {len(folders):,} shared folders · {self._human_bytes(total_folder_bytes)}"
            )
            latest_backup = self.connection.execute(
                """SELECT s.completed_at, s.imported_items, s.failed_items
                   FROM android_backup_snapshots s JOIN android_backup_profiles p ON p.id=s.profile_id
                   WHERE p.source_id=? AND s.status='COMPLETED'
                   ORDER BY s.completed_at DESC LIMIT 1""",
                (identity.source_id,),
            ).fetchone()
            if latest_backup is None:
                backup_text = "No backup completed yet"
            else:
                backup_text = f"Last backup {latest_backup[0]} · {latest_backup[1]:,} imported · {latest_backup[2]:,} failed"
            self.android_backup_summary.setText(
                f"{identity.display_name} · {device.get('media_count', 'unknown')} media items · "
                f"{len(folders)} shared folder(s) discovered · {backup_text}."
            )
            self._populate_android_folder_selector(folders)
            self._fill_table(
                self._tables["Android Devices"],
                ["Folder", "Items", "Bytes", "Images", "Videos"],
                [
                    (folder.relative_path, folder.count, folder.size_bytes, folder.image_count, folder.video_count)
                    for folder in folders
                ],
            )

        def _populate_android_folder_selector(self, folders: object) -> None:
            """Render the live Companion folder manifest as a checkable source picker."""
            if not hasattr(self, "android_folder_selector"):
                return
            selected = {
                line.strip().strip("/") for line in self.android_transfer_folders.toPlainText().splitlines()
                if line.strip()
            }
            if not selected:
                selected = {"DCIM/Camera"}
            self.android_folder_selector.blockSignals(True)
            self.android_folder_selector.clear()
            for folder in folders:
                path = str(folder.relative_path).strip("/")
                item = QListWidgetItem(f"{path}\n{int(folder.count):,} items · {self._human_bytes(int(folder.size_bytes))}")
                item.setData(Qt.ItemDataRole.UserRole, path)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if path in selected else Qt.CheckState.Unchecked)
                self.android_folder_selector.addItem(item)
            self.android_folder_selector.blockSignals(False)

        def _android_folder_selection_changed(self, _item: QListWidgetItem) -> None:
            selected = []
            for index in range(self.android_folder_selector.count()):
                item = self.android_folder_selector.item(index)
                if item.checkState() == Qt.CheckState.Checked:
                    selected.append(str(item.data(Qt.ItemDataRole.UserRole)))
            if selected:
                self.android_transfer_folders.setPlainText("\n".join(selected))

        def _android_failed(self, message: str) -> None:
            self.android_backup_status.setText("USB connection failed")
            self.android_device_card.setText("Android device\nUSB connection failed · Wi-Fi Companion is recommended")
            self.android_backup_summary.setText("Check the cable, USB mode, or use the Companion Wi-Fi connection.")
            self.android_result.setText(f"Android discovery failed: {message}")

        def _android_companion_failed(self, message: str) -> None:
            self.android_backup_status.setText("Phone connection failed")
            self.android_device_card.setText("Android device\nConnection failed · check sharing, network, and token")
            self.android_backup_summary.setText("Check that sharing is active, the Mac and phone are on the same Wi-Fi, and the token is current.")
            self.android_result.setText(f"Android Companion connection failed: {message}")

        def _android_thread_finished(self) -> None:
            self.android_discover_button.setEnabled(True)
            self._android_worker = None
            self._android_thread = None

        def _android_companion_thread_finished(self) -> None:
            self.android_companion_discover_button.setEnabled(True)
            self._android_companion_worker = None
            self._android_companion_thread = None

        def _android_transfer_thread_finished(self) -> None:
            self.android_transfer_button.setEnabled(True)
            self.android_transfer_cancel_button.setEnabled(False)
            self._android_transfer_worker = None
            self._android_transfer_thread = None

        @staticmethod
        def _human_bytes(value: float) -> str:
            units = ("B", "KiB", "MiB", "GiB", "TiB")
            magnitude = max(0.0, float(value))
            for unit in units:
                if magnitude < 1024 or unit == units[-1]:
                    return f"{magnitude:.1f} {unit}"
                magnitude /= 1024
            return f"{magnitude:.1f} TiB"

        @staticmethod
        def _human_duration(value: float) -> str:
            seconds = max(0, int(round(value)))
            hours, seconds = divmod(seconds, 3600)
            minutes, seconds = divmod(seconds, 60)
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"

        def _scan_completed(self, result: object) -> None:
            values = result
            self.scan_result.setText(f"Completed: {values['files_catalogued']} files, {values['errors']} errors")

        def _scan_failed(self, message: str) -> None:
            self.scan_result.setText(f"Scan failed: {message}")

        def _scan_thread_finished(self) -> None:
            self.scan_button.setEnabled(True)
            self.refresh()
            self._scan_worker = None
            self._scan_thread = None

        def _run_set_report(self, page: str) -> None:
            try:
                set_id = self._inputs[page].text().strip()
                if page == "Redundancy Audit":
                    from photovault.backup.audit import audit_backup_set

                    report = audit_backup_set(self.connection, set_id)
                    counts = ", ".join(f"{key}={value}" for key, value in report.counts.items() if value)
                    self._results[page].setText(f"{report.protected_count}/{report.total_assets} protected ({report.protection_percent:.1f}%). {counts}")
                else:
                    from photovault.backup.reconcile import reconcile_backup_set

                    report = reconcile_backup_set(self.connection, set_id)
                    counts = ", ".join(f"{key}={value}" for key, value in report.counts.items() if value)
                    self._results[page].setText(counts or "No catalogued files")
            except Exception as exc:
                self._results[page].setText(f"Report failed: {exc}")

        def _run_folder_report(self) -> None:
            try:
                from photovault.backup.folder_audit import audit_folder

                report = audit_folder(self.connection, Path(self._inputs["Folder Safety Audit"].text().strip()))
                status = "SAFE_CANDIDATE_FOR_REMOVAL" if report.safe_candidate else "NOT_SAFE_TO_DELETE"
                self._results["Folder Safety Audit"].setText(
                    f"{status}: scanned={report.files_scanned}, verified={report.verified_elsewhere}, "
                    f"unique={report.unique_files}, conflicts={report.conflicts}, offline={report.offline_unknown}, "
                    f"uncatalogued={report.uncatalogued}"
                )
            except Exception as exc:
                self._results["Folder Safety Audit"].setText(f"Audit failed: {exc}")

        def _build_copy_plan(self) -> None:
            try:
                from photovault.backup.copy import build_copy_plan

                plan = build_copy_plan(self.connection, self.copy_set_id.text().strip(), self.copy_backup_volume.text().strip() or None)
                self._copy_plan = plan
                self.copy_execute_button.setEnabled(bool(plan.items))
                self._fill_table(
                    self._tables["Copy Plans"],
                    ["Asset", "Source", "Destination", "Bytes", "SHA-256"],
                    [(item.asset_id, str(item.source_path), str(item.destination_path), item.size_bytes, item.expected_sha256) for item in plan.items],
                )
                self.copy_result.setText(f"Plan {plan.operation_id}: {len(plan.items)} file(s), {plan.total_bytes} bytes. Review it, then execute explicitly if the sources and destinations are correct.")
            except Exception as exc:
                self._copy_plan = None
                self.copy_execute_button.setEnabled(False)
                self.copy_result.setText(f"Copy-plan failed: {type(exc).__name__}: {exc}")

        def _build_quarantine_plan(self) -> None:
            try:
                from photovault.backup.quarantine import build_quarantine_plan

                paths = [Path(line.strip()) for line in self.quarantine_paths.toPlainText().splitlines() if line.strip()]
                plan = build_quarantine_plan(self.connection, paths, self.quarantine_reason.text().strip())
                self._quarantine_plan = plan
                self.quarantine_execute_button.setEnabled(bool(plan.items))
                self.quarantine_result.setText(
                    f"Plan {plan.operation_id}: {len(plan.items)} file(s). Manifest will be {plan.manifest_path}; "
                    "no file was moved. Review the manifest destination, then confirm execution."
                )
            except Exception as exc:
                self._quarantine_plan = None
                self.quarantine_execute_button.setEnabled(False)
                self.quarantine_result.setText(f"Quarantine-plan failed: {type(exc).__name__}: {exc}")

        def _execute_copy_plan(self) -> None:
            if self._copy_plan is None:
                return
            answer = QMessageBox.question(
                self,
                "Confirm verified copy",
                "Execute this reviewed copy plan? Sources are rehashed and conflicting destinations are never overwritten.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._start_operation(self._copy_plan, "copy")

        def _execute_quarantine_plan(self) -> None:
            if self._quarantine_plan is None:
                return
            answer = QMessageBox.question(
                self,
                "Confirm reversible quarantine",
                "Move the selected files into .PhotoVaultQuarantine after SHA-256 checks? This is reversible with undo-quarantine.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._start_operation(self._quarantine_plan, "quarantine")

        def _undo_quarantine(self) -> None:
            operation_id = self.undo_operation_id.text().strip()
            if not operation_id:
                self.undo_result.setText("Enter a completed QUARANTINE operation ID first.")
                return
            answer = QMessageBox.question(
                self,
                "Confirm quarantine undo",
                "Restore the quarantined files after SHA-256 checks? Conflicting originals will not be overwritten.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._start_operation(UndoQuarantineRequest(operation_id), "undo")

        def _start_operation(self, plan: object, kind: str) -> None:
            if self._catalog_path is None or (self._operation_thread is not None and self._operation_thread.isRunning()):
                return
            self._operation_kind = kind
            self._operation_thread = QThread(self)
            self._operation_worker = OperationWorker(self._catalog_path, plan)
            self._operation_worker.moveToThread(self._operation_thread)
            self._operation_thread.started.connect(self._operation_worker.run)
            self._operation_worker.completed.connect(self._operation_completed)
            self._operation_worker.failed.connect(self._operation_failed)
            self._operation_worker.completed.connect(self._operation_thread.quit)
            self._operation_worker.failed.connect(self._operation_thread.quit)
            self._operation_worker.completed.connect(self._operation_worker.deleteLater)
            self._operation_worker.failed.connect(self._operation_worker.deleteLater)
            self._operation_thread.finished.connect(self._operation_finished)
            self._operation_thread.finished.connect(self._operation_thread.deleteLater)
            if self._operation_kind == "copy":
                self.copy_execute_button.setEnabled(False)
                self.copy_result.setText("Executing verified copy in background…")
            elif self._operation_kind == "quarantine":
                self.quarantine_execute_button.setEnabled(False)
                self.quarantine_result.setText("Executing reversible quarantine in background…")
            else:
                self.undo_result.setText("Restoring quarantine in background…")
            self._operation_thread.start()

        def _operation_completed(self, result: object) -> None:
            if self._operation_kind == "copy":
                self.copy_result.setText(f"Copy complete: {result}")
            elif self._operation_kind == "quarantine":
                self.quarantine_result.setText(f"Quarantine complete: {result}")
            else:
                self.undo_result.setText(f"Quarantine undo complete: {result}")

        def _operation_failed(self, message: str) -> None:
            if self._operation_kind == "copy":
                self.copy_result.setText(f"Copy failed: {message}")
            elif self._operation_kind == "quarantine":
                self.quarantine_result.setText(f"Quarantine failed: {message}")
            else:
                self.undo_result.setText(f"Quarantine undo failed: {message}")

        def _operation_finished(self) -> None:
            self.refresh()
            self._operation_worker = None
            self._operation_thread = None
            self._operation_kind = None

        def _refresh_timeline(self) -> None:
            from photovault.catalog.timeline import list_timeline

            source_id = self.timeline_source_filter.currentData() if hasattr(self, "timeline_source_filter") else None
            page_size = int(self.timeline_page_size.currentData()) if hasattr(self, "timeline_page_size") else 500
            offset = int(getattr(self, "_timeline_offset", 0))
            rows = list_timeline(self.connection, limit=page_size, source_id=source_id, offset=offset)
            grouped = []
            for row in rows:
                day = str(row[5] or row[4] or "Undated")[:10]
                grouped.append((day, *row))
            self._fill_table(self._tables["Timeline"], ["Day", "Asset", "Filename", "Path", "Volume", "Captured", "Display time", "Camera", "Model", "W", "H", "Lat", "Lon", "Source", "Thumbnail"], grouped)
            if hasattr(self, "timeline_summary"):
                days = len({item[0] for item in grouped})
                start = offset + 1 if rows else 0
                end = offset + len(rows)
                self.timeline_summary.setText(f"Showing {start:,}–{end:,} item(s) across {days:,} day group(s). Display time includes the selected source offset; raw capture time is retained.")
            if hasattr(self, "timeline_previous"):
                self.timeline_previous.setEnabled(offset > 0)
            if hasattr(self, "timeline_next"):
                self.timeline_next.setEnabled(len(rows) == page_size)

        def _reset_timeline_page(self) -> None:
            self._timeline_offset = 0
            self._refresh_timeline()

        def _timeline_previous_page(self) -> None:
            page_size = int(self.timeline_page_size.currentData())
            self._timeline_offset = max(0, int(getattr(self, "_timeline_offset", 0)) - page_size)
            self._refresh_timeline()

        def _timeline_next_page(self) -> None:
            page_size = int(self.timeline_page_size.currentData())
            self._timeline_offset = int(getattr(self, "_timeline_offset", 0)) + page_size
            self._refresh_timeline()

        def _refresh_dashboard(self) -> None:
            from photovault.catalog.dashboard import dashboard_metrics

            metrics = dashboard_metrics(self.connection)
            if hasattr(self, "dashboard_cards"):
                android = self.connection.execute(
                    """SELECT display_name, adapter, last_seen
                       FROM source_profiles ORDER BY last_seen DESC LIMIT 1"""
                ).fetchone()
                backup_sets = int(self.connection.execute("SELECT COUNT(*) FROM backup_sets").fetchone()[0])
                self.dashboard_cards["safety"].setText(
                    "Backup configured\nRun Health Check"
                    if backup_sets else "Needs setup\nNo backup set configured"
                )
                self.dashboard_cards["library"].setText(f"{metrics.images:,} photos · {metrics.videos:,} videos")
                self.dashboard_cards["storage"].setText(f"{metrics.connected_volumes}/{metrics.volumes} drives connected")
                self.dashboard_cards["android"].setText(
                    f"{android[0]}\nLast seen {android[2]}" if android else "No phone connected\nOpen Android Devices to connect"
                )
                self.dashboard_cards["activity"].setText(
                    f"{metrics.active_operations} active operation(s)" if metrics.active_operations else "No active operations"
                )
            self.dashboard_result.setText(
                f"Library: {metrics.assets} assets ({metrics.images} images, {metrics.videos} videos). "
                f"Volumes: {metrics.connected_volumes}/{metrics.volumes} connected. "
                f"Last Android backup: {metrics.last_backup or 'none yet'}."
            )
            if hasattr(self, "dashboard_recent_grid"):
                self.dashboard_recent_grid.clear()
                recent = self.connection.execute(
                    """SELECT al.asset_id, al.filename, al.relative_path, th.path
                       FROM asset_locations al
                       JOIN assets a ON a.id=al.asset_id
                       LEFT JOIN media_metadata mm ON mm.asset_id=al.asset_id
                       LEFT JOIN thumbnails th ON th.asset_id=al.asset_id AND th.version='v1-320'
                       WHERE al.missing_since IS NULL
                       ORDER BY COALESCE(mm.capture_datetime, al.capture_date,
                                         datetime(al.modified_ns / 1000000000, 'unixepoch')) DESC
                       LIMIT 12"""
                ).fetchall()
                for row in recent:
                    item = QListWidgetItem(str(row[1]))
                    if row[3] and Path(str(row[3])).is_file():
                        item.setIcon(QIcon(str(row[3])))
                    item.setToolTip(str(row[2]))
                    item.setData(Qt.ItemDataRole.UserRole, str(row[1]))
                    self.dashboard_recent_grid.addItem(item)
                if not recent:
                    self.dashboard_recent_grid.show_empty_state("No photos indexed yet")
            self._fill_table(
                self._tables["Dashboard"], ["Metric", "Value"],
                [
                    ("Catalog size", self._human_bytes(metrics.catalog_bytes)),
                    ("Android devices", metrics.sources),
                    ("Android backup profiles", metrics.backup_profiles),
                    ("Favourites", metrics.favourites),
                    ("Place clusters", metrics.places),
                    ("Visual duplicate groups", metrics.duplicate_groups),
                    ("Active/partial operations", metrics.active_operations),
                ],
            )

        def _open_dashboard_item(self, item: QListWidgetItem) -> None:
            filename = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if not filename:
                return
            self.library_search.setText(filename)
            self._refresh_library()
            self._select_page("Library")

        def _refresh_library(self) -> None:
            try:
                from photovault.catalog.collections import collection_query
                from photovault.catalog.library import LibraryQuery, count_library_items, list_library_items

                limit = int(self.library_limit.text().strip())
                offset = int(getattr(self, "_library_offset", 0))
                base_query = LibraryQuery(
                    search=self.library_search.text(), folder_prefix=self.library_folder.text(),
                    media_type=self.library_media_type.currentText(),
                    favourite_only=self.library_favourites_only.isChecked(),
                    source_id=str(self.library_source_filter.currentData() or ""),
                    event_id=str(self.library_event_filter.currentData() or ""),
                    tag_id=str(self.library_tag_filter.currentData() or ""),
                    place_id=str(self.library_place_filter.currentData() or ""),
                    person_id=str(self.library_person_filter.currentData() or ""),
                    review_status=str(self.library_review_filter.currentData() or ""),
                    min_rating=self.library_rating_filter.currentData(),
                    include_rejected=self.library_include_rejected.isChecked(),
                    sort=str(self.library_sort.currentData()), limit=limit, offset=offset,
                )
                collection_filter = collection_query(self.connection, self._library_collection_id, limit=limit) if self._library_collection_id else LibraryQuery(limit=limit)
                query = LibraryQuery(
                    search=base_query.search,
                    folder_prefix=collection_filter.folder_prefix or base_query.folder_prefix,
                    media_type=base_query.media_type,
                    favourite_only=base_query.favourite_only or collection_filter.favourite_only,
                    captured_month=collection_filter.captured_month,
                    asset_ids=collection_filter.asset_ids,
                    source_id=base_query.source_id,
                    event_id=base_query.event_id,
                    tag_id=base_query.tag_id,
                    place_id=base_query.place_id,
                    person_id=base_query.person_id,
                    category=base_query.category,
                    review_status=base_query.review_status,
                    min_rating=base_query.min_rating,
                    include_rejected=base_query.include_rejected,
                    sort=base_query.sort, limit=limit, offset=offset,
                )
                rows = list_library_items(self.connection, query)
                total = count_library_items(self.connection, query)
                day_groups = len({str(row["display_captured"] or row["captured"] or "Undated")[:10] for row in rows})
                self.library_result.setText(
                    f"Showing {offset + 1 if rows else 0}–{offset + len(rows)} of {total} catalogued location(s). "
                    f"{day_groups:,} day group(s) on this page. "
                    "OFFLINE rows retain metadata and cached thumbnails; originals are not removed."
                )
                self.library_collection_result.setText(
                    f"Active collection: {self._library_collection_id}" if self._library_collection_id else "All catalogued media"
                )
                self._fill_table(
                    self._tables["Library"],
                    ["Asset", "Type", "Filename", "Path", "Bytes", "Volume", "State", "Captured", "Camera", "W", "H", "Favourite", "Thumbnail"],
                    [
                        (row["asset_id"], row["media_type"], row["filename"], row["relative_path"], row["size_bytes"],
                         row["volume_name"], row["volume_status"], row["captured"], row["camera_model"],
                         row["width"], row["height"], "★" if row["is_favourite"] else "", row["thumbnail_path"])
                        for row in rows
                    ],
                )
                self._populate_library_grid(rows)
                if hasattr(self, "library_previous"):
                    self.library_previous.setEnabled(offset > 0)
                if hasattr(self, "library_next"):
                    self.library_next.setEnabled(offset + len(rows) < total)
            except Exception as exc:
                self.library_result.setText(f"Library query failed: {type(exc).__name__}: {exc}")

        def _reset_library_page(self) -> None:
            self._library_offset = 0
            self._refresh_library()

        def _library_previous_page(self) -> None:
            limit = int(self.library_limit.text().strip())
            self._library_offset = max(0, int(getattr(self, "_library_offset", 0)) - limit)
            self._refresh_library()

        def _library_next_page(self) -> None:
            limit = int(self.library_limit.text().strip())
            self._library_offset = int(getattr(self, "_library_offset", 0)) + limit
            self._refresh_library()

        def _clear_library_collection(self) -> None:
            self._library_collection_id = None
            self._refresh_library()

        @staticmethod
        def _replace_library_filter(combo: QComboBox, placeholder: str, rows: object, label: object) -> None:
            """Rebuild a catalog filter while preserving its selected ID."""
            previous = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(placeholder, None)
            for row in rows:
                combo.addItem(str(label(row)), str(row.id))
            index = combo.findData(previous)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

        def _refresh_library_organisation_filters(self) -> None:
            """Populate human-readable organisation filters from catalog metadata."""
            from photovault.catalog.organization import list_events, list_places, list_sources, list_tags
            from photovault.catalog.people import list_people

            sources = list_sources(self.connection)
            events = list_events(self.connection)
            tags = list_tags(self.connection)
            places = list_places(self.connection)
            people = list_people(self.connection)
            source_previous = self.library_source_filter.currentData()
            self.library_source_filter.blockSignals(True)
            self.library_source_filter.clear()
            self.library_source_filter.addItem("Any source", None)
            for row in sources:
                detail = f"{row['display_name']} ({row['item_count']:,})"
                self.library_source_filter.addItem(detail, row["source_id"])
            self.library_source_filter.setCurrentIndex(max(0, self.library_source_filter.findData(source_previous)))
            self.library_source_filter.blockSignals(False)
            self._replace_library_filter(self.library_event_filter, "Any event", events, lambda row: f"{row.name} ({row.item_count:,})")
            self._replace_library_filter(self.library_tag_filter, "Any tag", tags, lambda row: f"{row.name} ({row.item_count:,})")
            self._replace_library_filter(self.library_place_filter, "Any place", places, lambda row: f"{row.name} ({row.item_count:,})")
            self._replace_library_filter(self.library_person_filter, "Any person", people, lambda row: f"{row.display_name or row.id} ({row.item_count:,})")
            self._replace_library_filter(self.library_assign_event, "Select event…", events, lambda row: f"{row.name} ({row.item_count:,})")
            self._replace_library_filter(self.library_assign_tag, "Select tag…", tags, lambda row: f"{row.name} ({row.item_count:,})")
            self._replace_library_filter(self.library_assign_place, "Select place…", places, lambda row: f"{row.name} ({row.item_count:,})")
            self._replace_library_filter(self.library_assign_person, "Select person…", people, lambda row: f"{row.display_name or row.id} ({row.item_count:,})")

        def _clear_library_organisation_filters(self) -> None:
            for combo in (self.library_source_filter, self.library_event_filter, self.library_tag_filter, self.library_place_filter,
                          self.library_person_filter, self.library_review_filter, self.library_rating_filter):
                combo.blockSignals(True)
                combo.setCurrentIndex(0)
                combo.blockSignals(False)
            self.library_include_rejected.setChecked(False)
            self._refresh_library()

        def _create_event(self) -> None:
            try:
                from photovault.catalog.organization import add_event_assets_in_date_range, create_event

                start = self.event_start.text().strip() or None
                end = self.event_end.text().strip() or None
                event_id = create_event(
                    self.connection,
                    self.event_name.text(),
                    start_datetime=start,
                    end_datetime=end,
                    event_type=str(self.event_type.currentData()),
                    default_place_id=self.event_default_place.currentData(),
                )
                added = add_event_assets_in_date_range(self.connection, event_id, start, end) if start and end else 0
                self.event_name.clear()
                self.event_start.clear()
                self.event_end.clear()
                suffix = f" Added {added:,} catalogued item(s) from the date range." if start and end else " Select media in Library to add items."
                self.events_result.setText("Event created." + suffix)
                self.refresh()
            except Exception as exc:
                self.events_result.setText(f"Event creation failed: {type(exc).__name__}: {exc}")

        def _selected_event_id(self) -> str | None:
            selected = self._tables["Events"].selectedItems()
            return str(self._tables["Events"].item(selected[0].row(), 0).data(Qt.ItemDataRole.UserRole)) if selected else None

        def _update_event(self) -> None:
            try:
                from photovault.catalog.organization import update_event

                event_id = self._selected_event_id()
                if not event_id:
                    raise ValueError("select an event first")
                update_event(self.connection, event_id, name=self.event_name.text(), start_datetime=self.event_start.text().strip() or None, end_datetime=self.event_end.text().strip() or None, event_type=str(self.event_type.currentData()), default_place_id=self.event_default_place.currentData())
                self.events_result.setText("Event updated. Original media was not changed.")
                self.refresh()
            except Exception as exc:
                self.events_result.setText(f"Event update failed: {type(exc).__name__}: {exc}")

        def _delete_event(self) -> None:
            try:
                from photovault.catalog.organization import delete_event

                event_id = self._selected_event_id()
                if not event_id:
                    raise ValueError("select an event first")
                delete_event(self.connection, event_id)
                self.events_result.setText("Event deleted from catalog; media files were not changed.")
                self.refresh()
            except Exception as exc:
                self.events_result.setText(f"Event deletion failed: {type(exc).__name__}: {exc}")

        def _refresh_events(self) -> None:
            from photovault.catalog.organization import list_events, list_places

            events = list_events(self.connection)
            self._fill_table(
                self._tables["Events"],
                ["Name", "Start", "End", "Type", "Items", "Suggested"],
                [(event.name, event.start_datetime or "—", event.end_datetime or "—", event.event_type, event.item_count, "Yes" if event.is_suggested else "No") for event in events],
            )
            for row, event in enumerate(events):
                self._tables["Events"].item(row, 0).setData(Qt.ItemDataRole.UserRole, event.id)
            self.events_result.setText(f"{len(events)} event(s). Double-click an event to filter Library.")
            if hasattr(self, "event_default_place"):
                self.event_default_place.blockSignals(True)
                self.event_default_place.clear()
                self.event_default_place.addItem("No default place", None)
                for place in list_places(self.connection):
                    self.event_default_place.addItem(place.name, place.id)
                self.event_default_place.blockSignals(False)

        def _load_event_row(self, row: int, _column: int) -> None:
            event_id = self._tables["Events"].item(row, 0).data(Qt.ItemDataRole.UserRole)
            from photovault.catalog.organization import list_events

            event = next((item for item in list_events(self.connection) if item.id == event_id), None)
            if event is None:
                return
            self.event_name.setText(event.name)
            self.event_start.setText(event.start_datetime or "")
            self.event_end.setText(event.end_datetime or "")
            type_index = self.event_type.findData(event.event_type)
            if type_index >= 0:
                self.event_type.setCurrentIndex(type_index)
            place_index = self.event_default_place.findData(event.default_place_id)
            self.event_default_place.setCurrentIndex(max(0, place_index))

        def _suggest_events(self) -> None:
            try:
                from photovault.catalog.organization import suggest_events_from_dates

                added = suggest_events_from_dates(self.connection)
                self.events_result.setText(f"Added {added} suggested event membership item(s). Manual events were preserved; originals were not changed.")
                self.refresh()
            except Exception as exc:
                self.events_result.setText(f"Event suggestion failed: {type(exc).__name__}: {exc}")

        def _open_event_row(self, row: int, _column: int) -> None:
            event_id = self._tables["Events"].item(row, 0).data(Qt.ItemDataRole.UserRole)
            if event_id:
                self._select_page("Library")
                index = self.library_event_filter.findData(event_id)
                if index >= 0:
                    self.library_event_filter.setCurrentIndex(index)
                self._refresh_library()

        def _create_tag(self) -> None:
            try:
                from photovault.catalog.organization import create_tag

                create_tag(self.connection, self.tag_name.text())
                self.tag_name.clear()
                self.tags_result.setText("Tag created. Select media in Library to assign it.")
                self.refresh()
            except Exception as exc:
                self.tags_result.setText(f"Tag creation failed: {type(exc).__name__}: {exc}")

        def _selected_tag_id(self) -> str | None:
            selected = self._tables["Tags"].selectedItems()
            return str(self._tables["Tags"].item(selected[0].row(), 0).data(Qt.ItemDataRole.UserRole)) if selected else None

        def _rename_tag(self) -> None:
            try:
                from photovault.catalog.organization import rename_tag

                tag_id = self._selected_tag_id()
                if not tag_id:
                    raise ValueError("select a tag first")
                rename_tag(self.connection, tag_id, self.tag_name.text())
                self.tags_result.setText("Tag renamed. Original media was not changed.")
                self.refresh()
            except Exception as exc:
                self.tags_result.setText(f"Tag rename failed: {type(exc).__name__}: {exc}")

        def _delete_tag(self) -> None:
            try:
                from photovault.catalog.organization import delete_tag

                tag_id = self._selected_tag_id()
                if not tag_id:
                    raise ValueError("select a tag first")
                delete_tag(self.connection, tag_id)
                self.tags_result.setText("Tag deleted from catalog; media files were not changed.")
                self.refresh()
            except Exception as exc:
                self.tags_result.setText(f"Tag deletion failed: {type(exc).__name__}: {exc}")

        def _create_manual_place(self) -> None:
            try:
                from photovault.catalog.organization import create_place

                create_place(self.connection, self.place_name.text(), city=self.place_city.text().strip() or None)
                self.place_name.clear()
                self.place_city.clear()
                self._results["Places"].setText("Manual place created. Select media in Library to assign it.")
                self.refresh()
            except Exception as exc:
                self._results["Places"].setText(f"Place creation failed: {type(exc).__name__}: {exc}")

        def _delete_manual_place(self) -> None:
            try:
                from photovault.catalog.organization import delete_place

                delete_place(self.connection, self.place_id_input.text().strip())
                self.place_id_input.clear()
                self._results["Places"].setText("Place deleted from catalog; media files were not changed.")
                self.refresh()
            except Exception as exc:
                self._results["Places"].setText(f"Place deletion failed: {type(exc).__name__}: {exc}")

        def _select_manual_place_row(self, row: int, _column: int) -> None:
            item = self._tables["Places"].item(row, 0)
            if item is None:
                return
            place_id = str(item.data(Qt.ItemDataRole.UserRole) or item.text())
            self.place_id_input.setText(place_id)
            name = self._tables["Places"].item(row, 1)
            city = self._tables["Places"].item(row, 2)
            self.place_name.setText(name.text() if name else "")
            self.place_city.setText(city.text() if city and city.text() != "—" else "")
            self.manual_places_hint.setText(f"Selected {place_id}. Edit the fields above, then update or delete it.")

        def _update_manual_place(self) -> None:
            try:
                from photovault.catalog.organization import update_place

                place_id = self.place_id_input.text().strip()
                if not place_id:
                    raise ValueError("select a place first")
                update_place(
                    self.connection,
                    place_id,
                    name=self.place_name.text(),
                    city=self.place_city.text().strip() or None,
                )
                self._results["Places"].setText("Place updated in catalog; media files were not changed.")
                self.refresh()
            except Exception as exc:
                self._results["Places"].setText(f"Place update failed: {type(exc).__name__}: {exc}")

        def _selected_library_asset_ids(self) -> list[str]:
            return [str(item.data(Qt.ItemDataRole.UserRole)["asset_id"]) for item in self.library_grid.selectedItems()]

        def _assign_selected_event(self) -> None:
            asset_ids = self._selected_library_asset_ids()
            event_id = self.library_assign_event.currentData()
            if not asset_ids or not event_id:
                self.library_result.setText("Select media and an event first.")
                return
            try:
                from photovault.catalog.organization import add_assets_to_event

                changed = add_assets_to_event(self.connection, str(event_id), asset_ids)
                self.library_result.setText(f"Added {changed} selected item(s) to the event. Originals were not changed.")
                self.refresh()
            except Exception as exc:
                self.library_result.setText(f"Event assignment failed: {type(exc).__name__}: {exc}")

        def _assign_selected_tag(self) -> None:
            asset_ids = self._selected_library_asset_ids()
            tag_id = self.library_assign_tag.currentData()
            if not asset_ids or not tag_id:
                self.library_result.setText("Select media and a tag first.")
                return
            try:
                from photovault.catalog.organization import assign_tags

                changed = assign_tags(self.connection, asset_ids, [str(tag_id)])
                self.library_result.setText(f"Assigned tag to {changed} selected item(s). Originals were not changed.")
                self.refresh()
            except Exception as exc:
                self.library_result.setText(f"Tag assignment failed: {type(exc).__name__}: {exc}")

        def _assign_selected_place(self) -> None:
            asset_ids = self._selected_library_asset_ids()
            place_id = self.library_assign_place.currentData()
            if not asset_ids or not place_id:
                self.library_result.setText("Select media and a place first.")
                return
            try:
                from photovault.catalog.organization import assign_place

                changed = assign_place(self.connection, asset_ids, str(place_id))
                self.library_result.setText(f"Assigned place to {changed} selected item(s). Originals were not changed.")
                self.refresh()
            except Exception as exc:
                self.library_result.setText(f"Place assignment failed: {type(exc).__name__}: {exc}")

        def _assign_selected_person(self) -> None:
            asset_ids = self._selected_library_asset_ids()
            person_id = self.library_assign_person.currentData()
            if not asset_ids or not person_id:
                self.library_result.setText("Select media and a person first.")
                return
            try:
                from photovault.catalog.people import assign_person

                changed = assign_person(self.connection, asset_ids, str(person_id))
                self.library_result.setText(f"Assigned person to {changed} selected item(s). Originals were not changed.")
                self.refresh()
            except Exception as exc:
                self.library_result.setText(f"Person assignment failed: {type(exc).__name__}: {exc}")

        def _remove_selected_event(self) -> None:
            asset_ids = self._selected_library_asset_ids()
            event_id = self.library_assign_event.currentData()
            if not asset_ids or not event_id:
                self.library_result.setText("Select media and an event first.")
                return
            try:
                from photovault.catalog.organization import remove_assets_from_event

                changed = remove_assets_from_event(self.connection, str(event_id), asset_ids)
                self.library_result.setText(f"Removed {changed} selected item(s) from the event. Originals were not changed.")
                self.refresh()
            except Exception as exc:
                self.library_result.setText(f"Event removal failed: {type(exc).__name__}: {exc}")

        def _remove_selected_tag(self) -> None:
            asset_ids = self._selected_library_asset_ids()
            tag_id = self.library_assign_tag.currentData()
            if not asset_ids or not tag_id:
                self.library_result.setText("Select media and a tag first.")
                return
            try:
                from photovault.catalog.organization import remove_tags

                changed = remove_tags(self.connection, asset_ids, [str(tag_id)])
                self.library_result.setText(f"Removed {changed} tag assignment(s). Originals were not changed.")
                self.refresh()
            except Exception as exc:
                self.library_result.setText(f"Tag removal failed: {type(exc).__name__}: {exc}")

        def _clear_selected_place(self) -> None:
            asset_ids = self._selected_library_asset_ids()
            place_id = self.library_assign_place.currentData()
            if not asset_ids or not place_id:
                self.library_result.setText("Select media and a place first.")
                return
            try:
                from photovault.catalog.organization import remove_place

                changed = remove_place(self.connection, asset_ids, str(place_id))
                self.library_result.setText(f"Cleared {changed} place assignment(s). Embedded GPS metadata was not changed.")
                self.refresh()
            except Exception as exc:
                self.library_result.setText(f"Place removal failed: {type(exc).__name__}: {exc}")

        def _refresh_tags(self) -> None:
            from photovault.catalog.organization import list_tags

            tags = list_tags(self.connection)
            self._fill_table(self._tables["Tags"], ["Tag", "Items"], [(tag.name, tag.item_count) for tag in tags])
            for row, tag in enumerate(tags):
                self._tables["Tags"].item(row, 0).setData(Qt.ItemDataRole.UserRole, tag.id)
            self.tags_result.setText(f"{len(tags)} tag(s). Double-click a tag to filter Library.")

        def _refresh_sources(self) -> None:
            from photovault.catalog.organization import list_sources

            rows = list_sources(self.connection)
            self._fill_table(
                self._tables["Sources"],
                ["Source", "Type", "Device", "Items", "Display offset", "Last seen"],
                [(row["display_name"], row["source_type"], f"{row['manufacturer']} {row['model']}", row["item_count"], f"{row['time_offset_seconds']} s", row["last_seen"] or "—") for row in rows],
            )
            for index, row in enumerate(rows):
                self._tables["Sources"].item(index, 0).setData(Qt.ItemDataRole.UserRole, row["source_id"])
            self.sources_result.setText(f"{len(rows)} source(s). Select a row to edit its display offset.")

        def _register_source_folder(self) -> None:
            try:
                from photovault.catalog.scanner import register_volume

                root = Path(self.source_folder_path.text().strip())
                volume_id = register_volume(self.connection, root)
                self.source_folder_volume_id = volume_id
                self.sources_result.setText(f"Registered folder source for {root} ({volume_id}). Choose Scan into Library to catalog its media.")
                self.refresh()
            except Exception as exc:
                self.sources_result.setText(f"Folder registration failed: {type(exc).__name__}: {exc}")

        def _scan_source_folder(self) -> None:
            try:
                if not self.source_folder_path.text().strip():
                    raise ValueError("folder path is required")
                self._register_source_folder()
                self.scan_volume_id.setText(str(getattr(self, "source_folder_volume_id", "")))
                self.scan_root.setText(self.source_folder_path.text().strip())
                self._select_page("Scan")
                self._scan()
                self.sources_result.setText("Folder scan started in the background. The source will appear in Library when complete.")
            except Exception as exc:
                self.sources_result.setText(f"Folder scan failed: {type(exc).__name__}: {exc}")

        def _select_source_row(self, row: int, _column: int) -> None:
            source_id = self._tables["Sources"].item(row, 0).data(Qt.ItemDataRole.UserRole)
            if source_id:
                self.source_id_input.setText(str(source_id))
                self.source_offset_input.setText(self._tables["Sources"].item(row, 4).text().removesuffix(" s"))

        def _apply_source_offset(self) -> None:
            try:
                from photovault.catalog.organization import set_source_time_offset

                set_source_time_offset(self.connection, self.source_id_input.text().strip(), int(self.source_offset_input.text().strip()))
                self.sources_result.setText("Display offset saved. Original capture metadata was not changed.")
                self.refresh()
            except Exception as exc:
                self.sources_result.setText(f"Source offset update failed: {type(exc).__name__}: {exc}")

        def _open_tag_row(self, row: int, _column: int) -> None:
            tag_id = self._tables["Tags"].item(row, 0).data(Qt.ItemDataRole.UserRole)
            if tag_id:
                self._select_page("Library")
                index = self.library_tag_filter.findData(tag_id)
                if index >= 0:
                    self.library_tag_filter.setCurrentIndex(index)
                self._refresh_library()

        def _open_review_queue(self, status: str) -> None:
            """Open a review queue in Library without changing any media bytes."""
            self._select_page("Library")
            index = self.library_review_filter.findData(status)
            if index >= 0:
                self.library_review_filter.setCurrentIndex(index)
            if not status:
                self.library_include_rejected.setChecked(False)
            self._refresh_library()
            if hasattr(self, "review_result"):
                self.review_result.setText("Review queue opened in Library. Select items and apply a catalog-only decision.")

        def _apply_selected_review(self) -> None:
            selected = self.library_grid.selectedItems()
            if not selected:
                self.library_result.setText("Select one or more items before applying a review decision.")
                return
            try:
                from photovault.catalog.organization import set_review

                status = str(self.library_review_action.currentData())
                asset_ids = [str(item.data(Qt.ItemDataRole.UserRole)["asset_id"]) for item in selected]
                changed = set_review(self.connection, asset_ids, status=status)
                self.library_result.setText(f"Updated review status for {changed} item(s). Originals were not changed.")
                self._refresh_library()
            except Exception as exc:
                self.library_result.setText(f"Review update failed: {type(exc).__name__}: {exc}")

        def _apply_selected_rating(self) -> None:
            selected = self.library_grid.selectedItems()
            rating = self.library_rating_action.currentData()
            if not selected or rating is None:
                self.library_result.setText("Select items and choose a rating first.")
                return
            try:
                from photovault.catalog.organization import set_review

                asset_ids = [str(item.data(Qt.ItemDataRole.UserRole)["asset_id"]) for item in selected]
                changed = set_review(self.connection, asset_ids, rating=int(rating))
                label = "cleared rating" if int(rating) == 0 else f"rated {rating}★"
                self.library_result.setText(f"{label.capitalize()} for {changed} item(s). Originals were not changed.")
                self._refresh_library()
            except Exception as exc:
                self.library_result.setText(f"Rating update failed: {type(exc).__name__}: {exc}")

        def _refresh_collections(self) -> None:
            try:
                from photovault.catalog.collections import list_collections

                collections = list_collections(self.connection)
                self._fill_table(
                    self._tables["Collections"], ["Collection ID", "Kind", "Title", "Items", "Evidence / note"],
                    [(item.id, item.kind, item.title, item.item_count, item.detail) for item in collections],
                )
                self.collections_result.setText(f"{len(collections)} collection(s), derived from the catalog without reading or changing originals.")
                if hasattr(self, "collections_grid"):
                    self.collections_grid.clear()
                    smart_collections = [item for item in collections if item.kind != "ALBUM"]
                    for collection in smart_collections:
                        tile = QListWidgetItem(f"{collection.title}\n{collection.item_count:,} items")
                        if collection.cover_path and Path(collection.cover_path).is_file():
                            tile.setIcon(QIcon(collection.cover_path))
                        tile.setToolTip(f"{collection.title}\n{collection.detail}")
                        tile.setData(Qt.ItemDataRole.UserRole, collection.id)
                        self.collections_grid.addItem(tile)
                    if not smart_collections:
                        self.collections_grid.addItem("No smart collections yet")
                if hasattr(self, "collections_album_grid"):
                    self.collections_album_grid.clear()
                    albums = [item for item in collections if item.kind == "ALBUM"]
                    for album in albums:
                        tile = QListWidgetItem(f"{album.title}\n{album.item_count:,} items")
                        if album.cover_path and Path(album.cover_path).is_file():
                            tile.setIcon(QIcon(album.cover_path))
                        tile.setToolTip(f"{album.title}\n{album.detail}")
                        tile.setData(Qt.ItemDataRole.UserRole, album.id)
                        self.collections_album_grid.addItem(tile)
                if hasattr(self, "library_collection_target"):
                    self.library_collection_target.blockSignals(True)
                    self.library_collection_target.clear()
                    self.library_collection_target.addItem("Select an album…", None)
                    for item in collections:
                        if item.kind == "ALBUM":
                            self.library_collection_target.addItem(f"{item.title} ({item.item_count})", item.id)
                    self.library_collection_target.blockSignals(False)
            except Exception as exc:
                self.collections_result.setText(f"Collection query failed: {type(exc).__name__}: {exc}")

        def _create_user_collection(self) -> None:
            try:
                from photovault.catalog.collections import create_user_collection

                collection_id = create_user_collection(self.connection, self.new_collection_title.text())
                self.new_collection_title.clear()
                self.collections_result.setText("Album created. Select photos in Library and add them to this album.")
                self.refresh()
                self.library_collection_target.setCurrentIndex(self.library_collection_target.findData(collection_id))
            except Exception as exc:
                self.collections_result.setText(f"Could not create album: {type(exc).__name__}: {exc}")

        def _open_album_tile(self, item: QListWidgetItem) -> None:
            collection_id = item.data(Qt.ItemDataRole.UserRole)
            if not collection_id:
                self.collections_result.setText("This album card is not actionable yet. Create an album and refresh collections first.")
                return
            self._open_collection_in_library(str(collection_id), self.collections_result)

        def _open_collection_tile(self, item: QListWidgetItem) -> None:
            collection_id = item.data(Qt.ItemDataRole.UserRole)
            if not collection_id:
                self.collections_result.setText("There are no smart collections to open yet. Index media or create an album first.")
                return
            self._open_collection_in_library(str(collection_id), self.collections_result)

        def _add_selected_to_collection(self) -> None:
            selected = self.library_grid.selectedItems()
            collection_id = self.library_collection_target.currentData()
            if not selected:
                self.library_result.setText("Select one or more photos first.")
                return
            if not collection_id:
                self.library_result.setText("Create or select an album first.")
                return
            try:
                from photovault.catalog.collections import add_to_user_collection

                asset_ids = [str(item.data(Qt.ItemDataRole.UserRole)["asset_id"]) for item in selected]
                added = add_to_user_collection(self.connection, str(collection_id), asset_ids)
                self.library_result.setText(
                    f"Added {added} photo(s) to the album. Existing album members were left unchanged; originals are untouched."
                )
                self.refresh()
            except Exception as exc:
                self.library_result.setText(f"Could not update album: {type(exc).__name__}: {exc}")

        def _refresh_backup_health(self) -> None:
            try:
                from photovault.backup.audit import audit_backup_set

                sets = self.connection.execute(
                    "SELECT id, name, required_copies FROM backup_sets ORDER BY name"
                ).fetchall()
                rows: list[tuple[object, ...]] = []
                total_assets = 0
                total_protected = 0
                total_issues = 0
                for backup_set in sets:
                    report = audit_backup_set(self.connection, str(backup_set[0]))
                    counts = report.counts
                    issues = report.total_assets - report.protected_count
                    total_assets += report.total_assets
                    total_protected += report.protected_count
                    total_issues += issues
                    rows.append((report.name, report.protected_count, report.total_assets, report.required_copies, issues))
                self._fill_table(
                    self._tables["Backup Health"],
                    ["Backup set", "Protected", "Assets", "Required copies", "Needs attention"],
                    rows,
                )
                if not sets:
                    self.backup_health_result.setText(
                        "No backup profiles have been configured yet. Create a Backup Set after registering a destination drive."
                    )
                elif total_issues:
                    self.backup_health_result.setText(
                        f"Needs attention · {total_protected:,}/{total_assets:,} assets currently meet their required verified copies; "
                        f"{total_issues:,} need review. No files were changed."
                    )
                else:
                    self.backup_health_result.setText(
                        f"All configured backup sets are healthy · {total_protected:,}/{total_assets:,} assets meet their required verified copies."
                    )
            except Exception as exc:
                self.backup_health_result.setText(f"Backup Health check failed: {type(exc).__name__}: {exc}")

        def _refresh_categories(self) -> None:
            try:
                from collections import defaultdict

                from photovault.catalog.category_taxonomy import normalize_label

                grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
                for row in self.connection.execute(
                    "SELECT model, label, asset_id FROM image_categories ORDER BY model, label, asset_id"
                ):
                    grouped[(str(row[0]), normalize_label(str(row[1])))].add(str(row[2]))
                table = self._tables["Categories"]
                table.setColumnCount(4)
                table.setHorizontalHeaderLabels(["Category", "Items", "Model", "Evidence / note"])
                table.setRowCount(len(grouped))
                for row_index, ((model, category), asset_ids) in enumerate(sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0]))):
                    values = (category, len(asset_ids), model, "normalised local model candidates")
                    for column_index, value in enumerate(values):
                        table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
                    table.item(row_index, 0).setData(Qt.ItemDataRole.UserRole, f"category:{model}:{category}")
                table.resizeColumnsToContents()
                self.category_grid.clear()
                for (model, category), asset_ids in sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0])):
                    category_id = f"category:{model}:{category}"
                    tile = QListWidgetItem(f"{category}\n{len(asset_ids):,} photos")
                    thumbnail = self.connection.execute(
                        """SELECT t.path FROM thumbnails t
                           WHERE t.asset_id=? AND t.version='v1-320' LIMIT 1""", (next(iter(asset_ids)),)
                    ).fetchone()
                    if thumbnail and Path(str(thumbnail[0])).is_file():
                        tile.setIcon(QIcon(str(thumbnail[0])))
                    tile.setToolTip(f"{category}\n{model}; {len(asset_ids):,} catalogued photo(s)")
                    tile.setData(Qt.ItemDataRole.UserRole, category_id)
                    self.category_grid.addItem(tile)
                if not grouped:
                    self.category_grid.show_empty_state("No categories indexed yet")
                self.categories_result.setText(
                    f"{len(grouped)} normalised local category view(s). Select one to browse its real photos; "
                    "categories remain rebuildable metadata, separate from backup protection."
                )
            except Exception as exc:
                self.categories_result.setText(f"Category query failed: {type(exc).__name__}: {exc}")

        def _refresh_backup_profiles(self) -> None:
            try:
                from photovault.backup.android_profiles import list_android_backup_profiles, profile_folders

                profiles = list_android_backup_profiles(self.connection)
                rows = []
                for profile in profiles:
                    folders = ", ".join(profile_folders(self.connection, str(profile["id"])))
                    rows.append((profile["id"], profile["name"], profile["source_id"], folders, profile["media_filter"], profile["destination_volume_name"], profile["last_completed_at"] or "Never"))
                table = self._tables["Backup Profiles"]
                table.setColumnCount(6)
                table.setHorizontalHeaderLabels(["Profile", "Phone", "Folders", "Media", "Destination", "Last backup"])
                table.setRowCount(len(rows))
                for row_index, row in enumerate(rows):
                    for column_index, value in enumerate(row[1:]):
                        table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
                    table.item(row_index, 0).setData(Qt.ItemDataRole.UserRole, row[0])
                table.resizeColumnsToContents()
                self.backup_profiles_result.setText(
                    f"{len(profiles):,} saved Android backup profile(s). Select one to load its current settings; no backup starts automatically."
                    if profiles else "No Android backup profiles yet. Connect a phone and complete a backup to save a reusable profile."
                )
            except Exception as exc:
                self.backup_profiles_result.setText(f"Could not load backup profiles: {type(exc).__name__}: {exc}")

        def _open_selected_backup_profile(self) -> None:
            selected = self._tables["Backup Profiles"].selectedItems()
            if not selected:
                self.backup_profiles_result.setText("Select one backup profile first.")
                return
            profile_id = self._tables["Backup Profiles"].item(selected[0].row(), 0).data(Qt.ItemDataRole.UserRole)
            self._open_backup_profile(str(profile_id))

        def _open_backup_profile_row(self, row: int, _column: int) -> None:
            self._tables["Backup Profiles"].selectRow(row)
            self._open_selected_backup_profile()

        def _open_backup_profile(self, profile_id: str) -> None:
            self._select_page("Android Devices")
            index = self.android_saved_profile.findData(profile_id)
            if index >= 0:
                self.android_saved_profile.setCurrentIndex(index)
                self._load_selected_android_backup_profile()
            else:
                self.android_result.setText("Saved profile is no longer available; refresh profiles and try again.")

        def _start_category_analysis(self) -> None:
            if self._classification_thread is not None and self._classification_thread.isRunning():
                return
            if self._catalog_path is None:
                self.categories_result.setText("A file-backed catalog is required before running local analysis.")
                return
            model = Path(self.category_model_path.text().strip()).expanduser()
            labels = Path(self.category_labels_path.text().strip()).expanduser()
            if not model.is_file() or not labels.is_file():
                self.categories_result.setText("Choose an existing local ONNX model and matching labels file first.")
                return
            try:
                limit = int(self.category_limit.text().strip())
                top_k = int(self.category_top_k.text().strip())
                if limit < 0 or top_k < 1:
                    raise ValueError
            except ValueError:
                self.categories_result.setText("Limit must be 0 or greater, and Top labels must be at least 1.")
                return
            self.category_start_button.setEnabled(False)
            self.category_cancel_button.setEnabled(True)
            self.category_progress.setValue(0)
            self.category_progress.setFormat("Starting…")
            self.categories_result.setText("Local category analysis is running in the background. Originals are read-only.")
            self._classification_thread = QThread(self)
            self._classification_worker = ClassificationWorker(self._catalog_path, model, labels, limit, top_k)
            self._classification_worker.moveToThread(self._classification_thread)
            self._classification_thread.started.connect(self._classification_worker.run)
            self._classification_worker.progress.connect(self._category_analysis_progress)
            self._classification_worker.completed.connect(self._category_analysis_completed)
            self._classification_worker.cancelled.connect(self._category_analysis_cancelled)
            self._classification_worker.failed.connect(self._category_analysis_failed)
            self._classification_worker.completed.connect(self._classification_thread.quit)
            self._classification_worker.cancelled.connect(self._classification_thread.quit)
            self._classification_worker.failed.connect(self._classification_thread.quit)
            self._classification_worker.completed.connect(self._classification_worker.deleteLater)
            self._classification_worker.cancelled.connect(self._classification_worker.deleteLater)
            self._classification_worker.failed.connect(self._classification_worker.deleteLater)
            self._classification_thread.finished.connect(self._classification_thread_finished)
            self._classification_thread.finished.connect(self._classification_thread.deleteLater)
            self._classification_thread.start()

        def _cancel_category_analysis(self) -> None:
            if self._classification_worker is not None:
                self._classification_worker.request_cancel()
                self.category_cancel_button.setEnabled(False)
                self.categories_result.setText("Cancellation requested; the current image will finish safely.")

        def _category_analysis_progress(self, event: object) -> None:
            total = int(event.get("assets", 0))
            processed = int(event.get("processed", 0))
            percent = int(processed / total * 100) if total else 0
            self.category_progress.setValue(max(0, min(percent, 100)))
            self.category_progress.setFormat(f"{processed:,}/{total:,} images")
            self.categories_result.setText(
                f"Analysing locally… {processed:,}/{total:,}; indexed {event.get('indexed', 0):,}, "
                f"skipped {event.get('skipped', 0):,}, errors {event.get('errors', 0):,}."
            )

        def _category_analysis_completed(self, result: object) -> None:
            self.category_progress.setValue(100)
            self.category_progress.setFormat("Complete")
            self.categories_result.setText(
                f"Category analysis complete: indexed {result['indexed']:,}, skipped {result['skipped']:,}, "
                f"errors {result['errors']:,} across {result['assets']:,} images."
            )
            self._refresh_categories()

        def _category_analysis_cancelled(self, message: str) -> None:
            self.category_progress.setFormat("Cancelled — safe to resume")
            self.categories_result.setText(f"Category analysis cancelled safely: {message}.")

        def _category_analysis_failed(self, message: str) -> None:
            self.category_progress.setFormat("Failed — review details")
            self.categories_result.setText(f"Category analysis failed: {message}")

        def _classification_thread_finished(self) -> None:
            self.category_start_button.setEnabled(True)
            self.category_cancel_button.setEnabled(False)
            self._classification_worker = None
            self._classification_thread = None

        def _open_selected_category(self) -> None:
            table = self._tables["Categories"]
            selected = table.selectedItems()
            if not selected:
                self.categories_result.setText("Select one category first.")
                return
            category_id = table.item(selected[0].row(), 0).data(Qt.ItemDataRole.UserRole)
            self._open_collection_in_library(str(category_id), self.categories_result)

        def _open_category_row(self, row: int, _column: int) -> None:
            table = self._tables["Categories"]
            table.selectRow(row)
            self._open_selected_category()

        def _open_category_tile(self, item: QListWidgetItem) -> None:
            category_id = item.data(Qt.ItemDataRole.UserRole)
            if category_id:
                self._open_collection_in_library(str(category_id), self.categories_result)

        def _open_person_tile(self, item: QListWidgetItem) -> None:
            person_id = item.data(Qt.ItemDataRole.UserRole)
            if person_id:
                self._open_collection_in_library(f"person:{person_id}", self.people_result)

        def _open_person_row(self, row: int, _column: int) -> None:
            table = self._tables["People"]
            table.selectRow(row)
            person_id = table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if person_id:
                self._open_collection_in_library(f"person:{person_id}", self.people_result)

        def _open_selected_collection(self) -> None:
            table = self._tables["Collections"]
            selected = table.selectedItems()
            if selected:
                collection_id = table.item(selected[0].row(), 0).text()
            else:
                # The visual cards are the primary interaction. Keep the
                # explicit button useful when a user single-clicks a card.
                card = next(iter(self.collections_grid.selectedItems()), None)
                if card is None and hasattr(self, "collections_album_grid"):
                    card = next(iter(self.collections_album_grid.selectedItems()), None)
                collection_id = card.data(Qt.ItemDataRole.UserRole) if card is not None else None
                if not collection_id:
                    self.collections_result.setText("Select a collection card or advanced-details row first.")
                    return
            self._open_collection_in_library(collection_id, self.collections_result)

        def _open_collection_in_library(self, collection_id: str, result_label: QLabel) -> None:
            try:
                from photovault.catalog.collections import collection_query

                selected_filter = collection_query(self.connection, collection_id, limit=int(self.library_limit.text().strip()))
                self._library_collection_id = collection_id
                if selected_filter.folder_prefix:
                    self.library_folder.setText(selected_filter.folder_prefix)
                self.library_favourites_only.setChecked(selected_filter.favourite_only)
                self._refresh_library()
                # Use the grouped-navigation selector so the visible sidebar and
                # stacked page always move together.  Setting a raw row index
                # bypasses that mapping when headings are present.
                self._select_page("Library")
            except ValueError as exc:
                if str(exc) == "collection has no members":
                    self._library_collection_id = collection_id
                    self.library_collection_result.setText(f"Active collection: {collection_id}")
                    self.library_result.setText("This collection is empty. Add photos from Library, then refresh.")
                    self._fill_table(self._tables["Library"], [], [])
                    self._populate_library_grid([])
                    self._select_page("Library")
                    return
                result_label.setText(f"Could not open collection: {type(exc).__name__}: {exc}")
            except Exception as exc:
                result_label.setText(f"Could not open collection: {type(exc).__name__}: {exc}")

        def _open_collection_row(self, row: int, _column: int) -> None:
            """Open a collection from the photo-first double-click interaction."""
            table = self._tables["Collections"]
            table.selectRow(row)
            self._open_selected_collection()

        def _import_people_features(self) -> None:
            try:
                from photovault.catalog.people_import import import_macos_vision_features_file

                report = import_macos_vision_features_file(self.connection, Path(self.people_features_json.text().strip()))
                self.people_result.setText(
                    f"Imported {report.people} person group(s), matching {report.matched_assets} asset(s); "
                    f"{report.unmatched_paths} path(s) were not in the connected catalog."
                )
                self.refresh()
            except Exception as exc:
                self.people_result.setText(f"People import failed: {type(exc).__name__}: {exc}")

        def _selected_person_id(self) -> str | None:
            selected = self._tables["People"].selectedItems()
            return str(self._tables["People"].item(selected[0].row(), 0).data(Qt.ItemDataRole.UserRole)) if selected else None

        def _create_person(self) -> None:
            try:
                from photovault.catalog.people import create_person

                create_person(self.connection, self.person_name.text())
                self.person_name.clear()
                self.people_result.setText("Person created. Select media in Library to assign this person.")
                self.refresh()
            except Exception as exc:
                self.people_result.setText(f"Person creation failed: {type(exc).__name__}: {exc}")

        def _load_person_row(self, row: int, _column: int) -> None:
            person_id = self._tables["People"].item(row, 0).data(Qt.ItemDataRole.UserRole)
            if person_id:
                name = self._tables["People"].item(row, 1)
                self.person_name.setText(name.text() if name else "")

        def _rename_person(self) -> None:
            try:
                from photovault.catalog.people import rename_person

                person_id = self._selected_person_id()
                if not person_id:
                    raise ValueError("select a person first")
                rename_person(self.connection, person_id, self.person_name.text())
                self.people_result.setText("Person renamed. Original media was not changed.")
                self.refresh()
            except Exception as exc:
                self.people_result.setText(f"Person rename failed: {type(exc).__name__}: {exc}")

        def _delete_person(self) -> None:
            try:
                from photovault.catalog.people import delete_person

                person_id = self._selected_person_id()
                if not person_id:
                    raise ValueError("select a person first")
                delete_person(self.connection, person_id)
                self.person_name.clear()
                self.people_result.setText("Person and its catalog assignments were deleted; original media was not changed.")
                self.refresh()
            except Exception as exc:
                self.people_result.setText(f"Person deletion failed: {type(exc).__name__}: {exc}")

        def _remove_selected_person(self) -> None:
            asset_ids = self._selected_library_asset_ids()
            person_id = self.library_assign_person.currentData()
            if not asset_ids or not person_id:
                self.library_result.setText("Select media and a person first.")
                return
            try:
                from photovault.catalog.people import remove_person

                changed = remove_person(self.connection, asset_ids, str(person_id))
                self.library_result.setText(f"Removed person assignment from {changed} selected item(s). Originals were not changed.")
                self.refresh()
            except Exception as exc:
                self.library_result.setText(f"Person removal failed: {type(exc).__name__}: {exc}")

        def _populate_library_grid(self, rows: list[sqlite3.Row]) -> None:
            if not rows:
                self.library_grid.show_empty_state("No photos indexed yet")
            else:
                self.library_grid.clear()
            self._viewer_items = []
            self._viewer_index = -1
            self.library_preview.setPixmap(QPixmap())
            self.library_preview.setText("Select a catalogued item to preview its cached thumbnail.")
            self.library_preview_details.setText("Original availability appears here.")
            for row in rows:
                display_time = row["display_captured"] or row["captured"]
                time_label = str(display_time)[:16].replace("T", " ") if display_time else "Undated"
                title = f"{'★ ' if row['is_favourite'] else ''}{row['filename']}\n{row['media_type']} · {time_label}"
                item = QListWidgetItem(title)
                thumbnail = str(row["thumbnail_path"] or "")
                if thumbnail and Path(thumbnail).is_file():
                    item.setIcon(QIcon(thumbnail))
                elif row["media_type"] == "VIDEO":
                    item.setText(title + "\n(video; no poster cached)")
                item.setToolTip(
                    f"{row['relative_path']}\n{row['volume_name']} ({row['volume_status']})\n"
                    f"Capture: {row['captured'] or 'unknown'}\n"
                    f"Display: {row['display_captured'] or 'unknown'}"
                )
                details = {
                    "asset_id": row["asset_id"], "filename": row["filename"],
                    "relative_path": row["relative_path"], "volume_name": row["volume_name"],
                    "volume_status": row["volume_status"], "thumbnail_path": thumbnail,
                    "is_favourite": bool(row["is_favourite"]), "media_type": row["media_type"],
                    "size_bytes": row["size_bytes"], "captured": row["captured"],
                    "camera_make": row["camera_make"], "camera_model": row["camera_model"],
                    "width": row["width"], "height": row["height"],
                    "latitude": row["latitude"], "longitude": row["longitude"],
                    "date_source": row["date_source"],
                    "source_name": row["source_name"], "review_status": row["review_status"],
                    "rating": row["rating"], "event_names": row["event_names"],
                    "tag_names": row["tag_names"], "place_names": row["place_names"],
                    "person_names": row["person_names"],
                }
                item.setData(Qt.ItemDataRole.UserRole, details)
                self.library_grid.addItem(item)
                self._viewer_items.append(details)

        def _set_library_technical_visible(self, visible: bool) -> None:
            self._tables["Library"].setVisible(visible)

        def _set_dashboard_technical_visible(self, visible: bool) -> None:
            self._tables["Dashboard"].setVisible(visible)

        def _set_collections_technical_visible(self, visible: bool) -> None:
            self._tables["Collections"].setVisible(visible)

        def _set_backup_health_technical_visible(self, visible: bool) -> None:
            self._tables["Backup Health"].setVisible(visible)

        def _set_disks_technical_visible(self, visible: bool) -> None:
            self._tables["Disks"].setVisible(visible)

        def _set_activity_technical_visible(self, visible: bool) -> None:
            self._tables["Operations"].setVisible(visible)

        def _open_library_item(self, item: QListWidgetItem) -> None:
            """Double-click opens the selected item in the dedicated viewer."""
            details = item.data(Qt.ItemDataRole.UserRole)
            self._viewer_index = next(
                (index for index, candidate in enumerate(self._viewer_items) if candidate["asset_id"] == details["asset_id"]),
                -1,
            )
            self._show_viewer_item(self._viewer_index)
            self._select_page("Photo Viewer")
            self.library_result.setText("Photo opened in Viewer. Use Back to Library to continue browsing.")

        def _library_context_menu(self, position: object) -> None:
            """Expose common library actions without exposing database internals."""
            item = self.library_grid.itemAt(position)
            if item is not None and item not in self.library_grid.selectedItems():
                self.library_grid.setCurrentItem(item)
            selected = self.library_grid.selectedItems()
            if not selected:
                return
            menu = QMenu(self)
            if len(selected) == 1:
                open_action = menu.addAction("Open in Viewer")
                open_action.triggered.connect(lambda: self._open_library_item(selected[0]))
            favourite_action = menu.addAction(
                "Remove favourite" if all(bool(i.data(Qt.ItemDataRole.UserRole)["is_favourite"]) for i in selected)
                else "Add favourite"
            )
            favourite_action.triggered.connect(self._toggle_selected_library_favourites)
            details_action = menu.addAction("Show file details")
            details_action.triggered.connect(self._library_selection_changed)
            menu.exec(self.library_grid.viewport().mapToGlobal(position))

        def _show_viewer_item(self, index: int) -> None:
            if not self._viewer_items:
                self._viewer_index = -1
                self.viewer_image.setPixmap(QPixmap())
                self.viewer_image.setText("Open a photo from Library to view it here.")
                self.viewer_details.setText("Photo details appear here.")
                return
            self._viewer_index = max(0, min(index, len(self._viewer_items) - 1))
            details = self._viewer_items[self._viewer_index]
            thumbnail = Path(str(details["thumbnail_path"])) if details["thumbnail_path"] else None
            if thumbnail is not None and thumbnail.is_file():
                pixmap = QPixmap(str(thumbnail))
                self.viewer_image.setPixmap(pixmap.scaled(
                    820, 620, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
                ))
                self.viewer_image.setText("")
            else:
                self.viewer_image.setPixmap(QPixmap())
                self.viewer_image.setText(
                    "No cached thumbnail is available. The catalog entry is still intact; return to Library for details."
                )
            self.viewer_details.setText(self._format_library_details(details))
            self.viewer_previous.setEnabled(self._viewer_index > 0)
            self.viewer_next.setEnabled(self._viewer_index < len(self._viewer_items) - 1)

        def _apply_viewer_review(self) -> None:
            if not self._viewer_items or self._viewer_index < 0:
                return
            try:
                from photovault.catalog.organization import set_review

                asset_id = str(self._viewer_items[self._viewer_index]["asset_id"])
                status = str(self.viewer_review_action.currentData())
                set_review(self.connection, [asset_id], status=status)
                self._viewer_items[self._viewer_index]["review_status"] = status
                self.viewer_details.setText(self._format_library_details(self._viewer_items[self._viewer_index]))
                self.library_result.setText(f"Marked {self._viewer_items[self._viewer_index]['filename']} as {status.title()}. Originals were not changed.")
            except Exception as exc:
                self.viewer_details.setText(f"Review update failed: {type(exc).__name__}: {exc}")

        def _apply_viewer_rating(self) -> None:
            if not self._viewer_items or self._viewer_index < 0:
                return
            rating = self.viewer_rating_action.currentData()
            if rating is None:
                return
            try:
                from photovault.catalog.organization import set_review

                details = self._viewer_items[self._viewer_index]
                set_review(self.connection, [str(details["asset_id"])], rating=int(rating))
                details["rating"] = None if int(rating) == 0 else int(rating)
                self.viewer_details.setText(self._format_library_details(details))
            except Exception as exc:
                self.viewer_details.setText(f"Rating update failed: {type(exc).__name__}: {exc}")

        def keyPressEvent(self, event: object) -> None:
            """Provide lightweight keyboard review controls in the viewer."""
            if self.pages.currentIndex() == NAVIGATION_ITEMS.index("Photo Viewer"):
                key = event.key()
                if key == Qt.Key.Key_Left:
                    self._show_viewer_item(self._viewer_index - 1)
                    return
                if key == Qt.Key.Key_Right:
                    self._show_viewer_item(self._viewer_index + 1)
                    return
                status = {Qt.Key.Key_P: "PICKED", Qt.Key.Key_R: "REJECTED", Qt.Key.Key_X: "REJECTED", Qt.Key.Key_H: "HIDDEN"}.get(key)
                if status:
                    index = self.viewer_review_action.findData(status)
                    if index >= 0:
                        self.viewer_review_action.setCurrentIndex(index)
                    self._apply_viewer_review()
                    return
                if key == Qt.Key.Key_F:
                    from photovault.catalog.favourites import remove_favourite, set_favourite

                    details = self._viewer_items[self._viewer_index]
                    if details.get("is_favourite"):
                        remove_favourite(self.connection, str(details["asset_id"]))
                        details["is_favourite"] = False
                    else:
                        set_favourite(self.connection, str(details["asset_id"]))
                        details["is_favourite"] = True
                    self.viewer_details.setText(self._format_library_details(details))
                    return
                if Qt.Key.Key_0 <= key <= Qt.Key.Key_5:
                    rating = key - Qt.Key.Key_0
                    index = self.viewer_rating_action.findData(rating)
                    if index >= 0:
                        self.viewer_rating_action.setCurrentIndex(index)
                    self._apply_viewer_rating()
                    return
            super().keyPressEvent(event)

        def _format_library_details(self, details: dict[str, object]) -> str:
            size = self._human_bytes(int(details["size_bytes"] or 0))
            dimensions = f"{details['width']} × {details['height']}" if details["width"] and details["height"] else "Dimensions unavailable"
            camera = " ".join(filter(None, (details["camera_make"], details["camera_model"]))) or "Camera unavailable"
            location = (
                f"{float(details['latitude']):.6f}, {float(details['longitude']):.6f} ({details['date_source'] or 'embedded metadata'})"
                if details["latitude"] is not None and details["longitude"] is not None else "No embedded location"
            )
            verified = self.connection.execute(
                "SELECT COUNT(DISTINCT path) FROM verification_history WHERE asset_id=? AND result='VERIFIED'",
                (details["asset_id"],),
            ).fetchone()[0]
            protection = f"Protected — {verified} verified copie{'s' if verified != 1 else ''}" if verified else "Not yet verified elsewhere"
            rating = f" · {details['rating']}★" if details.get("rating") is not None else ""
            return (
                f"{details['filename']}\n{details['captured'] or 'Date unavailable'}\n\n"
                f"Camera\n{camera}\n{dimensions} · {size}\n\nLocation\n{location}\n\n"
                f"Organisation\nSource: {details.get('source_name') or 'Unknown'}\n"
                f"Review: {details.get('review_status', 'UNREVIEWED').title()}{rating}\n"
                f"Event: {details.get('event_names') or '—'}\n"
                f"Tags: {details.get('tag_names') or '—'}\n"
                f"Place: {details.get('place_names') or '—'}\n"
                f"People: {details.get('person_names') or '—'}\n\n"
                f"File\n{details['relative_path']}\n{details['volume_name']} — {details['volume_status']}\n\n"
                f"Backup protection\n{protection}"
            )

        def _library_selection_changed(self) -> None:
            selected = self.library_grid.selectedItems()
            self.library_selection_count.setText(f"{len(selected)} selected")
            if not selected:
                return
            if len(selected) > 1:
                self.library_preview.setPixmap(QPixmap())
                self.library_preview.setText(f"{len(selected)} items selected")
                self.library_preview_details.setText("Use Toggle favourite to annotate all selected assets. No media files are changed.")
                return
            details = selected[0].data(Qt.ItemDataRole.UserRole)
            thumbnail = Path(str(details["thumbnail_path"])) if details["thumbnail_path"] else None
            if thumbnail is not None and thumbnail.is_file():
                pixmap = QPixmap(str(thumbnail))
                self.library_preview.setPixmap(pixmap.scaled(
                    320, 260, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
                ))
                self.library_preview.setText("")
            else:
                self.library_preview.setPixmap(QPixmap())
                label = "Video (no poster cached)" if details["media_type"] == "VIDEO" else "No cached thumbnail"
                self.library_preview.setText(label)
            availability = "Original is currently available" if details["volume_status"] == "CONNECTED" else "Original volume is offline; catalog/thumbnail remains available"
            self.library_preview_details.setText(self._format_library_details(details) + f"\n\n{availability}")

        def _toggle_selected_library_favourites(self) -> None:
            selected = self.library_grid.selectedItems()
            if not selected:
                self.library_result.setText("Select one or more items in the thumbnail grid first.")
                return
            try:
                from photovault.catalog.favourites import remove_favourite, set_favourite

                details = [item.data(Qt.ItemDataRole.UserRole) for item in selected]
                assets = {str(item["asset_id"]): bool(item["is_favourite"]) for item in details}
                remove = all(assets.values())
                for asset_id in assets:
                    if remove:
                        remove_favourite(self.connection, asset_id)
                    else:
                        set_favourite(self.connection, asset_id)
                self.library_result.setText(
                    f"{'Removed' if remove else 'Added'} favourite annotation for {len(assets)} asset(s). Originals and backups are unchanged."
                )
                self._refresh_library()
            except Exception as exc:
                self.library_result.setText(f"Favourite update failed: {type(exc).__name__}: {exc}")

        def _visual_duplicates(self, algorithm: QLineEdit, threshold: QLineEdit) -> None:
            try:
                from photovault.catalog.perceptual import find_visual_duplicate_groups

                groups = find_visual_duplicate_groups(self.connection, algorithm.text().strip(), int(threshold.text().strip()))
                self.duplicate_groups_list.clear()
                for group in groups:
                    members = group["members"]
                    item = QListWidgetItem(
                        f"{group['group_type'].replace('_', ' ').title()}\n"
                        f"{len(members)} similar photos · Review manually"
                    )
                    member_id = str(members[0]["asset_id"])
                    thumbnail = self.connection.execute(
                        "SELECT path FROM thumbnails WHERE asset_id=? AND version='v1-320' LIMIT 1",
                        (member_id,),
                    ).fetchone()
                    if thumbnail and Path(str(thumbnail[0])).is_file():
                        item.setIcon(QIcon(str(thumbnail[0])))
                    item.setData(Qt.ItemDataRole.UserRole, f"duplicate:{group['id']}")
                    item.setToolTip("Advisory similarity group. No deletion is performed.")
                    self.duplicate_groups_list.addItem(item)
                self._results["Visual Duplicates"].setText(
                    f"{len(groups)} advisory group(s). Review manually; no deletion is performed. "
                    + "; ".join(f"{group['id']} ({len(group['members'])} assets)" for group in groups)
                )
            except Exception as exc:
                self._results["Visual Duplicates"].setText(f"Similarity search failed: {exc}")

        def _open_duplicate_group(self, item: QListWidgetItem) -> None:
            self._open_collection_in_library(str(item.data(Qt.ItemDataRole.UserRole)), self._results["Visual Duplicates"])

        def _places(self, radius: QLineEdit) -> None:
            try:
                from photovault.catalog.places import cluster_places

                clusters = cluster_places(self.connection, float(radius.text().strip()))
                self._populate_places_grid(clusters)
                self._results["Places"].setText(
                    f"{len(clusters)} coordinate cluster(s), offline-safe. "
                    + "; ".join(f"{cluster.latitude:.4f},{cluster.longitude:.4f} ({len(cluster.asset_ids)} assets)" for cluster in clusters)
                )
            except Exception as exc:
                self._results["Places"].setText(f"Place clustering failed: {exc}")

        def _populate_places_grid(self, clusters: object) -> None:
            if not hasattr(self, "places_grid"):
                return
            self.places_grid.clear()
            for cluster in clusters:
                label = cluster.label or f"{cluster.latitude:.4f}, {cluster.longitude:.4f}"
                item = QListWidgetItem(f"{label}\n{len(cluster.asset_ids):,} photos")
                item.setToolTip(
                    f"{label}\n{cluster.latitude:.6f}, {cluster.longitude:.6f}\n"
                    f"Cluster radius {cluster.radius_meters:.1f} m; embedded GPS only"
                )
                thumbnail = self.connection.execute(
                    "SELECT path FROM thumbnails WHERE asset_id=? AND version='v1-320' LIMIT 1",
                    (cluster.asset_ids[0],),
                ).fetchone() if cluster.asset_ids else None
                if thumbnail and Path(str(thumbnail[0])).is_file():
                    item.setIcon(QIcon(str(thumbnail[0])))
                item.setData(Qt.ItemDataRole.UserRole, f"place:{cluster.id}")
                self.places_grid.addItem(item)
            if not clusters:
                self.places_grid.addItem("No embedded GPS clusters yet")

        def _open_place_tile(self, item: QListWidgetItem) -> None:
            collection_id = item.data(Qt.ItemDataRole.UserRole)
            if collection_id:
                self._open_collection_in_library(str(collection_id), self._results["Places"])

        def _set_favourite(self) -> None:
            try:
                from photovault.catalog.favourites import set_favourite

                asset_id = self.favourite_asset_id.text().strip()
                set_favourite(self.connection, asset_id, self.favourite_note.text())
                self.favourite_result.setText(f"Saved favourite annotation for {asset_id}.")
                self.refresh()
            except Exception as exc:
                self.favourite_result.setText(f"Favourite update failed: {type(exc).__name__}: {exc}")

        def _browse_favourites(self) -> None:
            self._library_collection_id = "favourites"
            self.library_favourites_only.setChecked(True)
            self._refresh_library()
            self._select_page("Library")

        def _remove_favourite(self) -> None:
            try:
                from photovault.catalog.favourites import remove_favourite

                asset_id = self.favourite_asset_id.text().strip()
                if remove_favourite(self.connection, asset_id):
                    self.favourite_result.setText(f"Removed favourite annotation for {asset_id}.")
                else:
                    self.favourite_result.setText(f"{asset_id} was not a favourite.")
                self.refresh()
            except Exception as exc:
                self.favourite_result.setText(f"Favourite removal failed: {type(exc).__name__}: {exc}")

        def _import_legacy_favourites(self) -> None:
            try:
                from photovault.catalog.favourites import import_legacy_favourites_json

                manifest = Path(self.favourite_legacy_manifest.text().strip())
                report = import_legacy_favourites_json(self.connection, manifest)
                self.favourite_result.setText(
                    f"Legacy import: {report.imported}/{report.declared} matched; "
                    f"unmatched={report.unmatched}, invalid={report.invalid}. No media files were changed."
                )
                self.refresh()
            except Exception as exc:
                self.favourite_result.setText(f"Legacy favourites import failed: {type(exc).__name__}: {exc}")

        def _fill_table(self, table: QTableWidget, headers: list[str], rows: list[tuple[object, ...]]) -> None:
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                for column_index, value in enumerate(row):
                    table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
            table.resizeColumnsToContents()

        def refresh(self) -> None:
            if "Dashboard" in self._tables:
                self._refresh_dashboard()
            if "Disks" in self._tables:
                from photovault.catalog.volume_state import refresh_volume_statuses

                refresh_volume_statuses(self.connection)
                rows = self.connection.execute("SELECT id, display_name, status, current_mount_path, last_seen FROM volumes ORDER BY display_name").fetchall()
                self._fill_table(self._tables["Disks"], ["Drive", "Status", "Location", "Last seen"], [(row[1], row[2], row[3], row[4]) for row in rows])
                if hasattr(self, "disks_grid"):
                    self.disks_grid.clear()
                    for volume_id, name, status, mount_path, last_seen in rows:
                        item = QListWidgetItem(f"{name}\n{status.title()}\n{mount_path or 'Not mounted'}")
                        item.setToolTip(f"Volume {volume_id}\nLast seen: {last_seen or 'Never'}")
                        self.disks_grid.addItem(item)
                    if not rows:
                        self.disks_grid.addItem("No registered drives yet")
                if hasattr(self, "disks_summary"):
                    connected = sum(row[2] == "CONNECTED" for row in rows)
                    self.disks_summary.setText(
                        f"{connected}/{len(rows)} drive(s) connected. Offline drives remain visible and are never treated as deleted."
                        if rows else "No drives registered yet. Register a mounted destination drive to start a verified backup."
                    )
            if "Backup Health" in self._tables:
                self._refresh_backup_health()
            if "Backup Sets" in self._tables:
                rows = self.connection.execute("SELECT id, name, required_copies, scope, updated_at FROM backup_sets ORDER BY name").fetchall()
                self._fill_table(self._tables["Backup Sets"], ["ID", "Name", "Required copies", "Scope", "Updated"], [tuple(row) for row in rows])
            if "Events" in self._tables:
                self._refresh_events()
            if "Tags" in self._tables:
                self._refresh_tags()
            if "Sources" in self._tables:
                self._refresh_sources()
            if "Places" in self._tables:
                from photovault.catalog.organization import list_places

                places = list_places(self.connection)
                self._fill_table(
                    self._tables["Places"],
                    ["Place ID", "Name", "City", "Country", "Items"],
                    [(place.id, place.name, place.city or "—", place.country or "—", place.item_count) for place in places],
                )
                for row, place in enumerate(places):
                    self._tables["Places"].item(row, 0).setData(Qt.ItemDataRole.UserRole, place.id)
                if hasattr(self, "manual_places_hint") and not places:
                    self.manual_places_hint.setText("No manual places yet. Create one above, or assign a place from Library.")
            if "Operations" in self._tables:
                rows = self.connection.execute("SELECT id, operation_type, status, dry_run, created_at, completed_at FROM operations ORDER BY created_at DESC").fetchall()
                labels = {
                    "IMPORT": "Backup import", "COPY": "Verified copy", "QUARANTINE": "Quarantine",
                    "UNDO_QUARANTINE": "Restore from quarantine", "SCAN": "Library scan",
                }
                self._fill_table(
                    self._tables["Operations"],
                    ["Activity", "Status", "Started", "Completed", "Details"],
                    [(labels.get(row[1], row[1].title()), row[2].title(), row[4], row[5] or "—", "Dry run" if row[3] else "") for row in rows],
                )
                if hasattr(self, "activity_feed"):
                    self.activity_feed.clear()
                    for row in rows[:12]:
                        label = labels.get(row[1], row[1].title())
                        state = row[2].title()
                        detail = "Dry run" if row[3] else "Verified catalog operation"
                        item = QListWidgetItem(f"{label} · {state}\n{row[4]}  {detail}")
                        item.setToolTip(f"Operation {row[0]}\nStarted: {row[4]}\nCompleted: {row[5] or 'In progress'}")
                        self.activity_feed.addItem(item)
                    if not rows:
                        self.activity_feed.addItem("No activity recorded yet")
                if hasattr(self, "activity_summary"):
                    self.activity_summary.setText(
                        f"{len(rows):,} recorded operation(s). Completed work remains auditable; technical operation IDs are available in Advanced details."
                        if rows else "No activity recorded yet. Completed scans and backups will appear here."
                    )
            if "Import Batches" in self._tables:
                from photovault.backup.source_import import list_import_batches

                batches = list_import_batches(self.connection, limit=50)
                self._fill_table(
                    self._tables["Import Batches"],
                    ["Batch", "Source", "Destination", "Status", "Started", "Completed", "Planned", "Imported", "Already", "Failed", "Bytes"],
                    [(
                        row["id"], row["source_name"], row["destination_volume_name"],
                        row["status"].title(), row["started_at"], row["completed_at"] or "—",
                        row["planned_items"], row["imported_items"], row["already_imported_items"],
                        row["failed_items"], self._human_bytes(row["imported_bytes"]),
                    ) for row in batches],
                )
                if hasattr(self, "import_batch_summary"):
                    active = sum(row["status"] == "RUNNING" for row in batches)
                    self.import_batch_summary.setText(
                        f"{len(batches):,} import batch(es) recorded; {active:,} currently running. "
                        "Counters include verified files only."
                        if batches else "No import batches recorded yet."
                    )
            if "Timeline" in self._tables:
                self._refresh_timeline()
            if "Library" in self._tables:
                self._refresh_library_organisation_filters()
                self._refresh_library()
            if "Collections" in self._tables:
                self._refresh_collections()
            if "Categories" in self._tables:
                self._refresh_categories()
            if "People" in self._tables:
                rows = self.connection.execute(
                    """SELECT p.id, p.display_name, p.engine, COUNT(m.asset_id), p.updated_at,
                              (SELECT t.path FROM person_members pm
                               JOIN thumbnails t ON t.asset_id=pm.asset_id AND t.version='v1-320'
                               WHERE pm.person_id=p.id ORDER BY pm.asset_id LIMIT 1)
                       FROM people p LEFT JOIN person_members m ON m.person_id=p.id
                       GROUP BY p.id ORDER BY COUNT(m.asset_id) DESC, p.id"""
                ).fetchall()
                self._fill_table(self._tables["People"], ["Person", "Name", "Engine", "Assets", "Updated"], [tuple(row[:5]) for row in rows])
                for row_index, row in enumerate(rows):
                    self._tables["People"].item(row_index, 0).setData(Qt.ItemDataRole.UserRole, str(row[0]))
                if hasattr(self, "people_grid"):
                    self.people_grid.clear()
                    for row in rows:
                        person_id, display_name, engine, count, _updated, cover_path = row
                        title = str(display_name or f"Person {str(person_id)[-6:]}")
                        tile = QListWidgetItem(f"{title}\n{int(count):,} photos")
                        if cover_path and Path(str(cover_path)).is_file():
                            tile.setIcon(QIcon(str(cover_path)))
                        tile.setToolTip(f"{title}\n{engine}; {count:,} catalogued photo(s)")
                        tile.setData(Qt.ItemDataRole.UserRole, str(person_id))
                        self.people_grid.addItem(tile)
                    if not rows:
                        self.people_grid.addItem("No people groups yet")
                    self.people_result.setText(
                        f"{len(rows):,} derived people group(s). Double-click a card to browse its catalogued photos."
                        if rows else "No people groups imported yet. Import macOS Vision derived memberships to begin."
                    )
            if hasattr(self, "android_saved_profile"):
                self._refresh_android_backup_profiles()
            if "Backup Profiles" in self._tables:
                self._refresh_backup_profiles()
            if "Favourites" in self._tables:
                from photovault.catalog.favourites import list_favourites

                rows = list_favourites(self.connection)
                self._fill_table(
                    self._tables["Favourites"],
                    ["Asset", "Note", "Updated", "Filename", "Path", "Volume", "Captured", "Thumbnail"],
                    [tuple(row) for row in rows],
                )


def run_gui(connection: sqlite3.Connection) -> int:
    _require_qt()
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(stylesheet())
    window = MainWindow(connection)
    window.show()
    return app.exec()
