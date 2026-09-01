"""Saved Android backup profiles page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QLabel, QPushButton, QTableWidget


def build_backup_profiles_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    owner.backup_profiles_result = QLabel(
        "Reusable Android backup recipes. A profile records the phone, selected folders, media filter, destination, and worker setting."
    )
    owner.backup_profiles_result.setObjectName("StatusSummary")
    owner.backup_profiles_result.setWordWrap(True)
    layout.addWidget(owner.backup_profiles_result)
    open_button = QPushButton("Open selected profile in Android Backup")
    open_button.clicked.connect(owner._open_selected_backup_profile)
    layout.addWidget(open_button)
    table = QTableWidget()
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.cellDoubleClicked.connect(owner._open_backup_profile_row)
    tables["Backup Profiles"] = table
    layout.addWidget(table)
