from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .spec import NAVIGATION_ITEMS

try:
    from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
    from PySide6.QtWidgets import (
        QApplication,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
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
            self._operation_thread: QThread | None = None
            self._operation_worker: OperationWorker | None = None
            self._operation_kind: str | None = None
            self._copy_plan = None
            self._quarantine_plan = None

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
            if label == "Scan":
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

        def _fill_table(self, table: QTableWidget, headers: list[str], rows: list[tuple[object, ...]]) -> None:
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                for column_index, value in enumerate(row):
                    table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
            table.resizeColumnsToContents()

        def refresh(self) -> None:
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


def run_gui(connection: sqlite3.Connection) -> int:
    _require_qt()
    app = QApplication.instance() or QApplication([])
    window = MainWindow(connection)
    window.show()
    return app.exec()
