from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from .spec import NAVIGATION_ITEMS

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
        QMessageBox,
        QPlainTextEdit,
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
            self.setWindowTitle("PhotoVault")
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

            shell = QWidget()
            shell_layout = QHBoxLayout(shell)
            self.navigation = QListWidget()
            self.navigation.addItems(list(NAVIGATION_ITEMS))
            self.navigation.setFixedWidth(220)
            self.navigation.currentRowChanged.connect(self._show_page)
            shell_layout.addWidget(self.navigation)

            self.pages = QStackedWidget()
            for label in NAVIGATION_ITEMS:
                self.pages.addWidget(self._build_page(label))
            shell_layout.addWidget(self.pages, 1)
            self.setCentralWidget(shell)
            self.navigation.setCurrentRow(0)
            self.refresh()

        def _build_page(self, label: str) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            title = QLabel(label)
            title.setStyleSheet("font-size: 24px; font-weight: 600; padding: 8px 0;")
            layout.addWidget(title)
            if label == "Dashboard":
                self.dashboard_result = QLabel("Loading catalog health…")
                self.dashboard_result.setWordWrap(True)
                layout.addWidget(self.dashboard_result)
                dashboard_table = QTableWidget()
                self._tables[label] = dashboard_table
                layout.addWidget(dashboard_table)
                button = QPushButton("Refresh dashboard")
                button.clicked.connect(self._refresh_dashboard)
                layout.addWidget(button)
            elif label == "Android Devices":
                form = QFormLayout()
                from photovault.cli.main import _default_android_helper

                self.android_companion_url = QLineEdit("http://")
                self.android_companion_token = QLineEdit()
                self.android_companion_token.setEchoMode(QLineEdit.EchoMode.Password)
                self.android_companion_token.setPlaceholderText("Token shown by PhotoVault Companion")
                form.addRow("Companion URL", self.android_companion_url)
                form.addRow("Companion token", self.android_companion_token)
                layout.addLayout(form)
                companion_button = QPushButton("Connect Companion (Wi-Fi)")
                companion_button.clicked.connect(self._discover_android_companion)
                self.android_companion_discover_button = companion_button
                layout.addWidget(companion_button)
                self.android_result = QLabel(
                    "Production path: connect the read-only Android Companion over Wi-Fi. "
                    "The device identity remains stable when its IP address changes."
                )
                self.android_result.setWordWrap(True)
                layout.addWidget(self.android_result)
                transfer_form = QFormLayout()
                self.android_transfer_folders = QPlainTextEdit("DCIM/Camera")
                self.android_transfer_folders.setPlaceholderText("One MediaStore relative folder per line, e.g. DCIM/Camera")
                self.android_transfer_profile_name = QLineEdit("Android Camera backup")
                self.android_transfer_media_filter = QComboBox()
                self.android_transfer_media_filter.addItem("Images and videos", "ALL")
                self.android_transfer_media_filter.addItem("Images only", "IMAGE")
                self.android_transfer_media_filter.addItem("Videos only", "VIDEO")
                self.android_transfer_destination = QLineEdit()
                self.android_transfer_workers = QLineEdit("5")
                transfer_form.addRow("Backup folders", self.android_transfer_folders)
                transfer_form.addRow("Profile name", self.android_transfer_profile_name)
                transfer_form.addRow("Media", self.android_transfer_media_filter)
                transfer_form.addRow("Destination directory", self.android_transfer_destination)
                transfer_form.addRow("Concurrent workers", self.android_transfer_workers)
                layout.addLayout(transfer_form)
                profile_actions = QHBoxLayout()
                self.android_saved_profile = QComboBox()
                self.android_saved_profile.setPlaceholderText("Saved backup profile")
                profile_actions.addWidget(self.android_saved_profile, 1)
                refresh_profiles_button = QPushButton("Refresh profiles")
                refresh_profiles_button.clicked.connect(self._refresh_android_backup_profiles)
                profile_actions.addWidget(refresh_profiles_button)
                load_profile_button = QPushButton("Load selected profile")
                load_profile_button.clicked.connect(self._load_selected_android_backup_profile)
                profile_actions.addWidget(load_profile_button)
                continue_profile_button = QPushButton("Continue selected backup")
                continue_profile_button.clicked.connect(self._continue_selected_android_backup_profile)
                profile_actions.addWidget(continue_profile_button)
                layout.addLayout(profile_actions)
                transfer_button = QPushButton("Start verified Wi-Fi backup")
                transfer_button.clicked.connect(self._start_android_companion_transfer)
                self.android_transfer_button = transfer_button
                layout.addWidget(transfer_button)
                cancel_transfer_button = QPushButton("Cancel transfer (partial files can resume)")
                cancel_transfer_button.setEnabled(False)
                cancel_transfer_button.clicked.connect(self._cancel_android_companion_transfer)
                self.android_transfer_cancel_button = cancel_transfer_button
                layout.addWidget(cancel_transfer_button)
                self.android_transfer_result = QLabel(
                    "A transfer copies new items only, SHA-256 verifies each completed file, and never changes phone files."
                )
                self.android_transfer_result.setWordWrap(True)
                layout.addWidget(self.android_transfer_result)
                self.android_profile_history = QTableWidget()
                layout.addWidget(QLabel("Saved profiles and recent runs"))
                layout.addWidget(self.android_profile_history)
                self.android_helper = QLineEdit(str(_default_android_helper()))
                form.addRow("Native helper", self.android_helper)
                button = QPushButton("Discover USB MTP (experimental macOS fallback)")
                button.clicked.connect(self._discover_android)
                self.android_discover_button = button
                layout.addWidget(button)
                table = QTableWidget()
                self._tables[label] = table
                layout.addWidget(table)
            elif label == "Scan":
                form = QFormLayout()
                self.scan_volume_id = QLineEdit()
                self.scan_root = QLineEdit()
                form.addRow("Volume ID", self.scan_volume_id)
                form.addRow("Mounted root", self.scan_root)
                layout.addLayout(form)
                button = QPushButton("Scan read-only")
                button.clicked.connect(self._scan)
                self.scan_button = button
                layout.addWidget(button)
                self.scan_result = QLabel("Ready")
                layout.addWidget(self.scan_result)
            elif label in {"Redundancy Audit", "Reconciliation"}:
                form = QFormLayout()
                set_id = QLineEdit()
                self._inputs[label] = set_id
                form.addRow("Backup set ID", set_id)
                layout.addLayout(form)
                button = QPushButton("Run read-only report")
                button.clicked.connect(lambda _checked=False, page=label: self._run_set_report(page))
                layout.addWidget(button)
                result = QLabel("Ready")
                result.setWordWrap(True)
                self._results[label] = result
                layout.addWidget(result)
            elif label == "Folder Safety Audit":
                form = QFormLayout()
                folder_path = QLineEdit()
                self._inputs[label] = folder_path
                form.addRow("Folder path", folder_path)
                layout.addLayout(form)
                button = QPushButton("Audit folder (read-only)")
                button.clicked.connect(self._run_folder_report)
                layout.addWidget(button)
                result = QLabel("Ready")
                result.setWordWrap(True)
                self._results[label] = result
                layout.addWidget(result)
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
                form = QFormLayout()
                self.library_search = QLineEdit()
                self.library_folder = QLineEdit()
                self.library_media_type = QComboBox()
                self.library_media_type.addItems(["ALL", "IMAGE", "VIDEO"])
                self.library_sort = QComboBox()
                self.library_sort.addItem("Capture date — newest", "captured_desc")
                self.library_sort.addItem("Capture date — oldest", "captured_asc")
                self.library_sort.addItem("Filename", "name_asc")
                self.library_sort.addItem("Largest first", "size_desc")
                self.library_favourites_only = QCheckBox("Favourites only")
                self.library_limit = QLineEdit("200")
                form.addRow("Search filename / path", self.library_search)
                form.addRow("Folder prefix", self.library_folder)
                form.addRow("Media", self.library_media_type)
                form.addRow("Sort", self.library_sort)
                form.addRow("Filter", self.library_favourites_only)
                form.addRow("Page size", self.library_limit)
                layout.addLayout(form)
                self.library_collection_result = QLabel("All catalogued media")
                self.library_collection_result.setWordWrap(True)
                layout.addWidget(self.library_collection_result)
                button = QPushButton("Refresh catalog library")
                button.clicked.connect(self._refresh_library)
                layout.addWidget(button)
                clear_collection_button = QPushButton("Clear collection filter")
                clear_collection_button.clicked.connect(self._clear_library_collection)
                layout.addWidget(clear_collection_button)
                favourite_button = QPushButton("Toggle favourite for selected item(s)")
                favourite_button.clicked.connect(self._toggle_selected_library_favourites)
                layout.addWidget(favourite_button)
                self.library_result = QLabel("Catalog-backed results remain visible when an original volume is offline.")
                self.library_result.setWordWrap(True)
                layout.addWidget(self.library_result)
                browser_layout = QHBoxLayout()
                self.library_grid = QListWidget()
                self.library_grid.setViewMode(QListWidget.ViewMode.IconMode)
                self.library_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
                self.library_grid.setIconSize(QSize(160, 120))
                self.library_grid.setGridSize(QSize(190, 170))
                self.library_grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
                self.library_grid.itemSelectionChanged.connect(self._library_selection_changed)
                browser_layout.addWidget(self.library_grid, 3)
                preview_layout = QVBoxLayout()
                self.library_preview = QLabel("Select a catalogued item to preview its cached thumbnail.")
                self.library_preview.setWordWrap(True)
                self.library_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.library_preview.setMinimumSize(260, 220)
                preview_layout.addWidget(self.library_preview)
                self.library_preview_details = QLabel("Original availability appears here.")
                self.library_preview_details.setWordWrap(True)
                preview_layout.addWidget(self.library_preview_details)
                browser_layout.addLayout(preview_layout, 2)
                layout.addLayout(browser_layout)
                table = QTableWidget()
                table.setSortingEnabled(True)
                self._tables[label] = table
                layout.addWidget(table)
            elif label == "Collections":
                self.collections_result = QLabel(
                    "Catalog-derived browse views: date, folders, favourites, embedded-GPS places, and advisory visual groups. No media files are changed."
                )
                self.collections_result.setWordWrap(True)
                layout.addWidget(self.collections_result)
                refresh_button = QPushButton("Refresh collections")
                refresh_button.clicked.connect(self._refresh_collections)
                layout.addWidget(refresh_button)
                open_button = QPushButton("Open selected collection in Library")
                open_button.clicked.connect(self._open_selected_collection)
                layout.addWidget(open_button)
                table = QTableWidget()
                table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
                table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
                self._tables[label] = table
                layout.addWidget(table)
            elif label in {"Timeline", "Visual Duplicates", "Places"}:
                if label == "Timeline":
                    button = QPushButton("Refresh timeline")
                    button.clicked.connect(self._refresh_timeline)
                    layout.addWidget(button)
                    table = QTableWidget()
                    self._tables[label] = table
                    layout.addWidget(table)
                elif label == "Visual Duplicates":
                    form = QFormLayout()
                    algorithm = QLineEdit("phash64")
                    threshold = QLineEdit("8")
                    form.addRow("Algorithm", algorithm)
                    form.addRow("Hamming threshold", threshold)
                    layout.addLayout(form)
                    button = QPushButton("Find advisory groups")
                    button.clicked.connect(lambda _checked=False, a=algorithm, t=threshold: self._visual_duplicates(a, t))
                    layout.addWidget(button)
                    result = QLabel("Visual similarity never authorizes deletion.")
                    result.setWordWrap(True)
                    self._results[label] = result
                    layout.addWidget(result)
                else:
                    form = QFormLayout()
                    radius = QLineEdit("100")
                    form.addRow("Cluster radius (m)", radius)
                    layout.addLayout(form)
                    button = QPushButton("Cluster GPS places")
                    button.clicked.connect(lambda _checked=False, r=radius: self._places(r))
                    layout.addWidget(button)
                    result = QLabel("No network geocoder is used by default.")
                    result.setWordWrap(True)
                    self._results[label] = result
                    layout.addWidget(result)
            elif label == "Favourites":
                form = QFormLayout()
                self.favourite_asset_id = QLineEdit()
                self.favourite_note = QLineEdit()
                self.favourite_legacy_manifest = QLineEdit()
                form.addRow("Catalog asset ID", self.favourite_asset_id)
                form.addRow("Note (optional)", self.favourite_note)
                form.addRow("Legacy favorites.json (optional)", self.favourite_legacy_manifest)
                layout.addLayout(form)
                favourite_button = QPushButton("Add / update favourite")
                favourite_button.clicked.connect(self._set_favourite)
                layout.addWidget(favourite_button)
                remove_button = QPushButton("Remove selected asset ID from favourites")
                remove_button.clicked.connect(self._remove_favourite)
                layout.addWidget(remove_button)
                import_button = QPushButton("Import legacy gallery favourites JSON")
                import_button.clicked.connect(self._import_legacy_favourites)
                layout.addWidget(import_button)
                self.favourite_result = QLabel("Favourites are catalog annotations only; originals and backup verification are unchanged.")
                self.favourite_result.setWordWrap(True)
                layout.addWidget(self.favourite_result)
                table = QTableWidget()
                table.setSortingEnabled(True)
                self._tables[label] = table
                layout.addWidget(table)
            elif label == "Disks":
                form = QFormLayout()
                self.disk_root = QLineEdit()
                form.addRow("Mounted folder / disk root", self.disk_root)
                layout.addLayout(form)
                button = QPushButton("Register disk (catalog only)")
                button.clicked.connect(self._register_disk)
                layout.addWidget(button)
                self.disk_result = QLabel("No files are changed by registration.")
                self.disk_result.setWordWrap(True)
                layout.addWidget(self.disk_result)
                table = QTableWidget()
                table.setSortingEnabled(True)
                self._tables[label] = table
                layout.addWidget(table)
            elif label == "Backup Sets":
                create_form = QFormLayout()
                self.backup_set_name = QLineEdit()
                self.backup_set_copies = QLineEdit("2")
                self.backup_set_scope = QLineEdit()
                create_form.addRow("Name", self.backup_set_name)
                create_form.addRow("Required verified copies", self.backup_set_copies)
                create_form.addRow("Scope (optional)", self.backup_set_scope)
                layout.addLayout(create_form)
                create_button = QPushButton("Create backup set")
                create_button.clicked.connect(self._create_backup_set)
                layout.addWidget(create_button)
                member_form = QFormLayout()
                self.member_set_id = QLineEdit()
                self.member_volume_id = QLineEdit()
                self.member_role = QLineEdit("BACKUP")
                self.member_relative_root = QLineEdit()
                member_form.addRow("Set ID", self.member_set_id)
                member_form.addRow("Volume ID", self.member_volume_id)
                member_form.addRow("Role (PRIMARY/BACKUP)", self.member_role)
                member_form.addRow("Relative root", self.member_relative_root)
                layout.addLayout(member_form)
                member_button = QPushButton("Add set member")
                member_button.clicked.connect(self._add_backup_member)
                layout.addWidget(member_button)
                self.backup_set_result = QLabel("Backup sets change catalog policy only.")
                self.backup_set_result.setWordWrap(True)
                layout.addWidget(self.backup_set_result)
                table = QTableWidget()
                table.setSortingEnabled(True)
                self._tables[label] = table
                layout.addWidget(table)
            elif label == "Operations":
                form = QFormLayout()
                self.undo_operation_id = QLineEdit()
                form.addRow("Quarantine operation ID", self.undo_operation_id)
                layout.addLayout(form)
                undo_button = QPushButton("Undo completed quarantine")
                undo_button.clicked.connect(self._undo_quarantine)
                layout.addWidget(undo_button)
                self.undo_result = QLabel("Undo re-hashes the quarantined file and never overwrites a conflicting original.")
                self.undo_result.setWordWrap(True)
                layout.addWidget(self.undo_result)
                table = QTableWidget()
                table.setSortingEnabled(True)
                self._tables[label] = table
                layout.addWidget(table)
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
                self.android_transfer_result.setText("Reading Android folder inventory…")
            elif stage == "planned":
                self._android_transfer_total = int(event["items"])
                bytes_total = int(event["bytes_total"])
                self._android_transfer_total_bytes = bytes_total
                conflicts = int(event["conflicts"])
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
            self.android_transfer_result.setText(
                f"Backup complete: imported {result['imported']}, already verified {result['already_imported']}, "
                f"planned {result['planned']}; {self._human_bytes(self._android_transfer_bytes)} at "
                f"{self._human_bytes(average)}/s over {self._human_duration(elapsed)}; "
                f"resumed {self._human_bytes(resumed)}. Destination volume: {result['destination_volume']}."
            )
            self._refresh_android_backup_profiles()
            self.refresh()

        def _android_transfer_cancelled(self, message: str) -> None:
            self.android_transfer_result.setText(f"Backup cancelled safely: {message}. Retained partial files can resume.")
            self._refresh_android_backup_profiles()

        def _android_transfer_failed(self, message: str) -> None:
            self.android_transfer_result.setText(f"Android backup failed: {message}")
            self._refresh_android_backup_profiles()

        def _android_completed(self, result: object) -> None:
            identity = result["identity"]
            storages = result["storages"]
            self.android_result.setText(
                f"{identity.display_name} connected via {identity.adapter}. "
                f"{len(storages)} storage(s) discovered."
            )
            self._fill_table(
                self._tables["Android Devices"],
                ["Storage ID", "Name", "Capacity", "Free"],
                [(storage.storage_id, storage.name, storage.capacity_bytes, storage.free_bytes) for storage in storages],
            )

        def _android_companion_completed(self, result: object) -> None:
            identity = result["identity"]
            device = result["device"]
            folders = result["folders"]
            self.android_result.setText(
                f"Connected to {identity.display_name} via Wi-Fi. Device ID: {identity.source_id}. "
                f"Media: {device.get('media_count', 'unknown')}. "
                f"Companion version: {device.get('app_version', 'unknown')}."
            )
            self._fill_table(
                self._tables["Android Devices"],
                ["Folder", "Items", "Bytes", "Images", "Videos"],
                [
                    (folder.relative_path, folder.count, folder.size_bytes, folder.image_count, folder.video_count)
                    for folder in folders
                ],
            )

        def _android_failed(self, message: str) -> None:
            self.android_result.setText(f"Android discovery failed: {message}")

        def _android_companion_failed(self, message: str) -> None:
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

            rows = list_timeline(self.connection, limit=500)
            self._fill_table(self._tables["Timeline"], ["Asset", "Filename", "Path", "Volume", "Captured", "Camera", "Model", "W", "H", "Lat", "Lon", "Thumbnail"], rows)

        def _refresh_dashboard(self) -> None:
            from photovault.catalog.dashboard import dashboard_metrics

            metrics = dashboard_metrics(self.connection)
            self.dashboard_result.setText(
                f"Library: {metrics.assets} assets ({metrics.images} images, {metrics.videos} videos). "
                f"Volumes: {metrics.connected_volumes}/{metrics.volumes} connected. "
                f"Last Android backup: {metrics.last_backup or 'none yet'}."
            )
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

        def _refresh_library(self) -> None:
            try:
                from photovault.catalog.collections import collection_query
                from photovault.catalog.library import LibraryQuery, count_library_items, list_library_items

                limit = int(self.library_limit.text().strip())
                base_query = LibraryQuery(
                    search=self.library_search.text(), folder_prefix=self.library_folder.text(),
                    media_type=self.library_media_type.currentText(),
                    favourite_only=self.library_favourites_only.isChecked(),
                    sort=str(self.library_sort.currentData()), limit=limit,
                )
                collection_filter = collection_query(self.connection, self._library_collection_id, limit=limit) if self._library_collection_id else LibraryQuery(limit=limit)
                query = LibraryQuery(
                    search=base_query.search,
                    folder_prefix=collection_filter.folder_prefix or base_query.folder_prefix,
                    media_type=base_query.media_type,
                    favourite_only=base_query.favourite_only or collection_filter.favourite_only,
                    captured_month=collection_filter.captured_month,
                    asset_ids=collection_filter.asset_ids,
                    sort=base_query.sort, limit=limit,
                )
                rows = list_library_items(self.connection, query)
                total = count_library_items(self.connection, query)
                self.library_result.setText(
                    f"Showing {len(rows)} of {total} catalogued location(s). "
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
            except Exception as exc:
                self.library_result.setText(f"Library query failed: {type(exc).__name__}: {exc}")

        def _clear_library_collection(self) -> None:
            self._library_collection_id = None
            self._refresh_library()

        def _refresh_collections(self) -> None:
            try:
                from photovault.catalog.collections import list_collections

                collections = list_collections(self.connection)
                self._fill_table(
                    self._tables["Collections"], ["Collection ID", "Kind", "Title", "Items", "Evidence / note"],
                    [(item.id, item.kind, item.title, item.item_count, item.detail) for item in collections],
                )
                self.collections_result.setText(f"{len(collections)} collection(s), derived from the catalog without reading or changing originals.")
            except Exception as exc:
                self.collections_result.setText(f"Collection query failed: {type(exc).__name__}: {exc}")

        def _open_selected_collection(self) -> None:
            table = self._tables["Collections"]
            selected = table.selectedItems()
            if not selected:
                self.collections_result.setText("Select one collection row first.")
                return
            collection_id = table.item(selected[0].row(), 0).text()
            try:
                from photovault.catalog.collections import collection_query

                selected_filter = collection_query(self.connection, collection_id, limit=int(self.library_limit.text().strip()))
                self._library_collection_id = collection_id
                if selected_filter.folder_prefix:
                    self.library_folder.setText(selected_filter.folder_prefix)
                self.library_favourites_only.setChecked(selected_filter.favourite_only)
                self._refresh_library()
                self.navigation.setCurrentRow(NAVIGATION_ITEMS.index("Library"))
            except Exception as exc:
                self.collections_result.setText(f"Could not open collection: {type(exc).__name__}: {exc}")

        def _populate_library_grid(self, rows: list[sqlite3.Row]) -> None:
            self.library_grid.clear()
            self.library_preview.setPixmap(QPixmap())
            self.library_preview.setText("Select a catalogued item to preview its cached thumbnail.")
            self.library_preview_details.setText("Original availability appears here.")
            for row in rows:
                title = f"{'★ ' if row['is_favourite'] else ''}{row['filename']}\n{row['media_type']}"
                item = QListWidgetItem(title)
                thumbnail = str(row["thumbnail_path"] or "")
                if thumbnail and Path(thumbnail).is_file():
                    item.setIcon(QIcon(thumbnail))
                elif row["media_type"] == "VIDEO":
                    item.setText(title + "\n(video; no poster cached)")
                item.setToolTip(f"{row['relative_path']}\n{row['volume_name']} ({row['volume_status']})")
                item.setData(Qt.ItemDataRole.UserRole, {
                    "asset_id": row["asset_id"], "filename": row["filename"],
                    "relative_path": row["relative_path"], "volume_name": row["volume_name"],
                    "volume_status": row["volume_status"], "thumbnail_path": thumbnail,
                    "is_favourite": bool(row["is_favourite"]), "media_type": row["media_type"],
                })
                self.library_grid.addItem(item)

        def _library_selection_changed(self) -> None:
            selected = self.library_grid.selectedItems()
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
            self.library_preview_details.setText(
                f"{details['filename']}\n{details['relative_path']}\n{details['volume_name']}: {availability}"
            )

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
                self._results["Visual Duplicates"].setText(
                    f"{len(groups)} advisory group(s). Review manually; no deletion is performed. "
                    + "; ".join(f"{group['id']} ({len(group['members'])} assets)" for group in groups)
                )
            except Exception as exc:
                self._results["Visual Duplicates"].setText(f"Similarity search failed: {exc}")

        def _places(self, radius: QLineEdit) -> None:
            try:
                from photovault.catalog.places import cluster_places

                clusters = cluster_places(self.connection, float(radius.text().strip()))
                self._results["Places"].setText(
                    f"{len(clusters)} coordinate cluster(s), offline-safe. "
                    + "; ".join(f"{cluster.latitude:.4f},{cluster.longitude:.4f} ({len(cluster.asset_ids)} assets)" for cluster in clusters)
                )
            except Exception as exc:
                self._results["Places"].setText(f"Place clustering failed: {exc}")

        def _set_favourite(self) -> None:
            try:
                from photovault.catalog.favourites import set_favourite

                asset_id = self.favourite_asset_id.text().strip()
                set_favourite(self.connection, asset_id, self.favourite_note.text())
                self.favourite_result.setText(f"Saved favourite annotation for {asset_id}.")
                self.refresh()
            except Exception as exc:
                self.favourite_result.setText(f"Favourite update failed: {type(exc).__name__}: {exc}")

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
                self._fill_table(self._tables["Disks"], ["ID", "Name", "Status", "Mount path", "Last seen"], [tuple(row) for row in rows])
            if "Backup Sets" in self._tables:
                rows = self.connection.execute("SELECT id, name, required_copies, scope, updated_at FROM backup_sets ORDER BY name").fetchall()
                self._fill_table(self._tables["Backup Sets"], ["ID", "Name", "Required copies", "Scope", "Updated"], [tuple(row) for row in rows])
            if "Operations" in self._tables:
                rows = self.connection.execute("SELECT id, operation_type, status, dry_run, created_at, completed_at FROM operations ORDER BY created_at DESC").fetchall()
                self._fill_table(self._tables["Operations"], ["ID", "Type", "Status", "Dry run", "Created", "Completed"], [tuple(row) for row in rows])
            if "Timeline" in self._tables:
                self._refresh_timeline()
            if "Library" in self._tables:
                self._refresh_library()
            if hasattr(self, "android_saved_profile"):
                self._refresh_android_backup_profiles()
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
    window = MainWindow(connection)
    window.show()
    return app.exec()
