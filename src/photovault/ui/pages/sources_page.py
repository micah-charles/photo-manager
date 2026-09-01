"""First-class source provenance and display offset page."""
from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidget


def build_sources_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    intro = QLabel(
        "Sources identify where media came from. Time offsets affect display ordering only; raw capture metadata and original files stay unchanged."
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)
    folder_form = QFormLayout()
    owner.source_folder_path = QLineEdit()
    owner.source_folder_path.setPlaceholderText("/Volumes/CameraSD or /Users/.../Photos")
    folder_form.addRow("Folder / SD path", owner.source_folder_path)
    layout.addLayout(folder_form)
    folder_actions = QHBoxLayout()
    register_folder = QPushButton("Register folder source")
    register_folder.clicked.connect(owner._register_source_folder)
    folder_actions.addWidget(register_folder)
    scan_folder = QPushButton("Scan into Library")
    scan_folder.clicked.connect(owner._scan_source_folder)
    folder_actions.addWidget(scan_folder)
    layout.addLayout(folder_actions)
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
