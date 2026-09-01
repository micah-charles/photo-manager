"""Timeline page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QTableWidget


def build_timeline_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    button = QPushButton("Refresh timeline")
    button.clicked.connect(owner._refresh_timeline)
    layout.addWidget(button)
    table = QTableWidget()
    tables["Timeline"] = table
    layout.addWidget(table)
