"""Drives page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QListWidget, QPushButton, QTableWidget

from ..components import configure_tile_grid


def build_disks_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    """Build the user-facing drive overview and its advanced detail table."""
    owner.disks_summary = QLabel("Your registered storage locations and current connection state.")
    owner.disks_summary.setObjectName("StatusSummary")
    owner.disks_summary.setWordWrap(True)
    layout.addWidget(owner.disks_summary)

    form = QFormLayout()
    owner.disk_root = QLineEdit()
    owner.disk_root.setPlaceholderText("/path/to/mounted-destination")
    form.addRow("Mounted folder / disk root", owner.disk_root)
    layout.addLayout(form)

    button = QPushButton("Register disk (catalog only)")
    button.setToolTip("Register a destination identity without scanning or changing files.")
    button.clicked.connect(owner._register_disk)
    layout.addWidget(button)

    owner.disk_result = QLabel("No files are changed by registration.")
    owner.disk_result.setWordWrap(True)
    layout.addWidget(owner.disk_result)
    layout.addWidget(QLabel("Storage locations"))

    owner.disks_grid = QListWidget()
    configure_tile_grid(owner.disks_grid, "DisksGrid", icon_size=(64, 64), grid_size=(220, 125))
    owner.disks_grid.setToolTip("Select a drive to inspect its catalog status below.")
    layout.addWidget(owner.disks_grid)

    table = QTableWidget()
    table.setSortingEnabled(True)
    tables["Disks"] = table
    layout.addWidget(table)
