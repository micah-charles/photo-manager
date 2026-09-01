"""Backup Health page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton, QTableWidget


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
    layout.addWidget(table)
