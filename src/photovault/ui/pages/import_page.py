"""General mounted-folder and camera-card import entry point."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton


def build_import_page(owner: object, layout: object) -> None:
    intro = QLabel(
        "Import photos from a mounted folder or camera/SD card. Catalog in Place leaves files where they are; Managed Copy uses a reviewed copy plan."
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)
    form = QFormLayout()
    owner.import_folder_path = QLineEdit()
    owner.import_folder_path.setAccessibleName("Import source folder")
    owner.import_folder_path.setPlaceholderText("/path/to/CameraSD or /path/to/Photos")
    source_row = QHBoxLayout()
    source_row.addWidget(owner.import_folder_path, 1)
    browse = QPushButton("Browse…")
    browse.clicked.connect(owner._choose_import_folder)
    source_row.addWidget(browse)
    form.addRow("Source folder / SD card", source_row)
    owner.import_mode = QComboBox()
    owner.import_mode.addItem("Catalog in Place (no copy)", "catalog")
    owner.import_mode.addItem("Managed Copy (review plan)", "managed")
    form.addRow("Import mode", owner.import_mode)
    owner.import_destination = QLineEdit()
    owner.import_destination.setPlaceholderText("Destination is chosen in the reviewed copy workflow")
    owner.import_destination.setReadOnly(True)
    form.addRow("Destination", owner.import_destination)
    layout.addLayout(form)
    preview = QPushButton("Preview source contents")
    preview.setToolTip("Counts supported image and video files without changing the source or catalog.")
    preview.clicked.connect(owner._preview_import_folder)
    layout.addWidget(preview)
    start = QPushButton("Start import")
    start.clicked.connect(owner._start_general_import)
    layout.addWidget(start)
    owner.import_result = QLabel("No import started. Source files are never modified by Catalog in Place.")
    owner.import_result.setWordWrap(True)
    layout.addWidget(owner.import_result)
