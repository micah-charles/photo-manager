"""Timeline page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QTableWidget


def build_timeline_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    controls = QHBoxLayout()
    owner.timeline_source_filter = QComboBox()
    owner.timeline_source_filter.addItem("All sources", None)
    owner.timeline_source_filter.currentIndexChanged.connect(owner._refresh_timeline)
    controls.addWidget(QLabel("Source"))
    controls.addWidget(owner.timeline_source_filter, 1)
    button = QPushButton("Refresh timeline")
    button.clicked.connect(owner._refresh_timeline)
    controls.addWidget(button)
    layout.addLayout(controls)
    owner.timeline_summary = QLabel("Unified chronological view across catalogued sources.")
    owner.timeline_summary.setWordWrap(True)
    layout.addWidget(owner.timeline_summary)
    table = QTableWidget()
    tables["Timeline"] = table
    layout.addWidget(table)
