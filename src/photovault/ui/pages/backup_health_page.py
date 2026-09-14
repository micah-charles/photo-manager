"""Backup Health page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton, QTableWidget


def build_backup_health_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    owner.backup_health_result = QLabel("No health check has been run yet.")
    owner.backup_health_result.setObjectName("StatusSummary")
    owner.backup_health_result.setWordWrap(True)
    layout.addWidget(owner.backup_health_result)
    button = QPushButton("Run Backup Health check")
    button.clicked.connect(owner._refresh_backup_health)
    layout.addWidget(button)
    table = QTableWidget()
    tables["Backup Health"] = table
    table.setVisible(False)
    layout.addWidget(table)
    owner.backup_health_technical_toggle = QCheckBox("Show detailed backup-set audit")
    owner.backup_health_technical_toggle.toggled.connect(owner._set_backup_health_technical_visible)
    layout.addWidget(owner.backup_health_technical_toggle)
