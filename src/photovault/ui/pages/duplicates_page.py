"""Visual duplicate review page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QListWidget, QPushButton


def build_duplicates_page(owner: object, layout: object) -> None:
    button = QPushButton("Find advisory groups")
    button.clicked.connect(lambda: owner._visual_duplicates(owner.duplicate_algorithm, owner.duplicate_threshold))
    layout.addWidget(button)
    configure = QPushButton("Configure analysis in Settings")
    configure.clicked.connect(lambda: owner._select_page("Settings"))
    layout.addWidget(configure)
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
