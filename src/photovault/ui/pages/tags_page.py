"""User tag management page."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidget


def build_tags_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    intro = QLabel("Tags are user-controlled labels and remain separate from AI categories.")
    intro.setWordWrap(True)
    layout.addWidget(intro)
    actions = QHBoxLayout()
    owner.tag_name = QLineEdit()
    owner.tag_name.setPlaceholderText("New tag name")
    actions.addWidget(owner.tag_name, 1)
    create = QPushButton("Create tag")
    create.clicked.connect(owner._create_tag)
    actions.addWidget(create)
    refresh = QPushButton("Refresh tags")
    refresh.clicked.connect(owner._refresh_tags)
    actions.addWidget(refresh)
    layout.addLayout(actions)
    owner.tags_result = QLabel("Tags are catalog metadata.")
    owner.tags_result.setWordWrap(True)
    layout.addWidget(owner.tags_result)
    table = QTableWidget()
    table.cellDoubleClicked.connect(owner._open_tag_row)
    tables["Tags"] = table
    layout.addWidget(table)
