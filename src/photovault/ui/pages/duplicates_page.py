"""Visual duplicate review page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QFormLayout, QLabel, QLineEdit, QListWidget, QPushButton, QWidget


def build_duplicates_page(owner: object, layout: object) -> None:
    advanced_toggle = QCheckBox("Show advanced duplicate-analysis settings")
    layout.addWidget(advanced_toggle)
    advanced_body = QWidget()
    advanced_body.setVisible(False)
    form = QFormLayout(advanced_body)
    algorithm = QLineEdit("phash64")
    threshold = QLineEdit("8")
    form.addRow("Algorithm", algorithm)
    form.addRow("Hamming threshold", threshold)
    advanced_toggle.toggled.connect(advanced_body.setVisible)
    layout.addWidget(advanced_body)
    button = QPushButton("Find advisory groups")
    button.clicked.connect(lambda _checked=False, a=algorithm, t=threshold: owner._visual_duplicates(a, t))
    layout.addWidget(button)
    result = QLabel("Visual similarity never authorizes deletion.")
    result.setWordWrap(True)
    owner._results["Visual Duplicates"] = result
    layout.addWidget(result)
    owner.duplicate_groups_list = QListWidget()
    owner.duplicate_groups_list.setObjectName("ReviewList")
    owner.duplicate_groups_list.itemDoubleClicked.connect(owner._open_duplicate_group)
    owner.duplicate_groups_list.addItem("No duplicate groups found")
    layout.addWidget(QLabel("Review groups — double-click to browse"))
    layout.addWidget(owner.duplicate_groups_list)
