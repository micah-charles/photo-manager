"""First-class source provenance and display offset page."""
from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QPushButton, QTableWidget


def build_sources_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    intro = QLabel(
        "Sources identify where media came from. Time offsets affect display ordering only; raw capture metadata and original files stay unchanged."
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)
    form = QFormLayout()
    owner.source_id_input = QLineEdit()
    owner.source_id_input.setPlaceholderText("Select a source row below")
    owner.source_offset_input = QLineEdit("0")
    owner.source_offset_input.setPlaceholderText("Seconds, e.g. 3600")
    form.addRow("Source ID", owner.source_id_input)
    form.addRow("Display offset", owner.source_offset_input)
    layout.addLayout(form)
    apply_button = QPushButton("Apply display offset")
    apply_button.clicked.connect(owner._apply_source_offset)
    layout.addWidget(apply_button)
    refresh_button = QPushButton("Refresh sources")
    refresh_button.clicked.connect(owner._refresh_sources)
    layout.addWidget(refresh_button)
    owner.sources_result = QLabel("Sources are catalog provenance records.")
    owner.sources_result.setWordWrap(True)
    layout.addWidget(owner.sources_result)
    table = QTableWidget()
    table.cellClicked.connect(owner._select_source_row)
    tables["Sources"] = table
    layout.addWidget(table)
