"""People/face-group page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QFormLayout, QLabel, QLineEdit, QListWidget, QPushButton, QTableWidget

from ..components import configure_tile_grid


def build_people_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    form = QFormLayout()
    owner.people_features_json = QLineEdit()
    owner.people_features_json.setPlaceholderText("Read-only macOS Vision features JSON")
    form.addRow("Vision features JSON", owner.people_features_json)
    layout.addLayout(form)
    import_button = QPushButton("Import macOS Vision people groups")
    import_button.clicked.connect(owner._import_people_features)
    layout.addWidget(import_button)
    owner.people_result = QLabel(
        "This imports only derived face-group memberships. It never modifies originals; rerunning replaces the prior macOS Vision grouping."
    )
    owner.people_result.setWordWrap(True)
    layout.addWidget(owner.people_result)
    layout.addWidget(QLabel("Browse people groups"))
    owner.people_grid = QListWidget()
    configure_tile_grid(owner.people_grid, "PeopleGrid", icon_size=(120, 100), grid_size=(170, 145))
    owner.people_grid.itemClicked.connect(owner._open_person_tile)
    owner.people_grid.itemDoubleClicked.connect(owner._open_person_tile)
    layout.addWidget(owner.people_grid)
    table = QTableWidget()
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.cellDoubleClicked.connect(owner._open_person_row)
    table.setSortingEnabled(True)
    tables["People"] = table
    layout.addWidget(table)
