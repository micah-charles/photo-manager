"""Timeline page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QPushButton, QTableWidget


def build_timeline_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    controls = QHBoxLayout()
    owner.timeline_source_filter = QComboBox()
    owner.timeline_source_filter.setAccessibleName("Timeline source filter")
    owner.timeline_source_filter.addItem("All sources", None)
    owner.timeline_source_filter.currentIndexChanged.connect(owner._reset_timeline_page)
    controls.addWidget(QLabel("Source"))
    controls.addWidget(owner.timeline_source_filter, 1)
    button = QPushButton("Refresh timeline")
    button.clicked.connect(owner._refresh_timeline)
    controls.addWidget(button)
    controls.addWidget(QLabel("Page size"))
    owner.timeline_page_size = QComboBox()
    owner.timeline_page_size.setAccessibleName("Timeline page size")
    for size in (100, 500, 1000):
        owner.timeline_page_size.addItem(str(size), size)
    owner.timeline_page_size.setCurrentIndex(1)
    owner.timeline_page_size.currentIndexChanged.connect(owner._reset_timeline_page)
    controls.addWidget(owner.timeline_page_size)
    owner.timeline_previous = QPushButton("Previous")
    owner.timeline_previous.clicked.connect(owner._timeline_previous_page)
    owner.timeline_previous.setEnabled(False)
    controls.addWidget(owner.timeline_previous)
    owner.timeline_next = QPushButton("Next")
    owner.timeline_next.clicked.connect(owner._timeline_next_page)
    controls.addWidget(owner.timeline_next)
    layout.addLayout(controls)
    owner.timeline_summary = QLabel("Unified chronological view across catalogued sources.")
    owner.timeline_summary.setWordWrap(True)
    layout.addWidget(owner.timeline_summary)
    table = QTableWidget()
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setToolTip("Double-click a row to open the photo in Viewer")
    table.cellDoubleClicked.connect(owner._open_timeline_row)
    tables["Timeline"] = table
    layout.addWidget(table)
