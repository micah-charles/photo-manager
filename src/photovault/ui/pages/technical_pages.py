"""Progressively-disclosed technical safety page builders."""
from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QPushButton


def build_scan_page(owner: object, layout: object) -> None:
    form = QFormLayout()
    owner.scan_volume_id = QLineEdit()
    owner.scan_root = QLineEdit()
    form.addRow("Volume ID", owner.scan_volume_id)
    form.addRow("Mounted root", owner.scan_root)
    layout.addLayout(form)
    button = QPushButton("Scan read-only")
    button.clicked.connect(owner._scan)
    owner.scan_button = button
    layout.addWidget(button)
    owner.scan_result = QLabel("Ready")
    owner.scan_result.setWordWrap(True)
    layout.addWidget(owner.scan_result)


def build_set_report_page(owner: object, layout: object, page: str) -> None:
    form = QFormLayout()
    set_id = QLineEdit()
    owner._inputs[page] = set_id
    form.addRow("Backup set ID", set_id)
    layout.addLayout(form)
    button = QPushButton("Run read-only report")
    button.clicked.connect(lambda _checked=False, target=page: owner._run_set_report(target))
    layout.addWidget(button)
    result = QLabel("Ready")
    result.setWordWrap(True)
    owner._results[page] = result
    layout.addWidget(result)


def build_folder_safety_page(owner: object, layout: object) -> None:
    form = QFormLayout()
    folder_path = QLineEdit()
    owner._inputs["Folder Safety Audit"] = folder_path
    form.addRow("Folder path", folder_path)
    layout.addLayout(form)
    button = QPushButton("Audit folder (read-only)")
    button.clicked.connect(owner._run_folder_report)
    layout.addWidget(button)
    result = QLabel("Ready")
    result.setWordWrap(True)
    owner._results["Folder Safety Audit"] = result
    layout.addWidget(result)
