"""People/face-group page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QTableWidget, QWidget

from ..components import configure_tile_grid


def build_people_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    advanced_toggle = QCheckBox("Show advanced face-analysis import")
    layout.addWidget(advanced_toggle)
    advanced_body = QWidget()
    advanced_body.setVisible(False)
    form = QFormLayout(advanced_body)
    owner.people_features_json = QLineEdit()
    owner.people_features_json.setPlaceholderText("Read-only macOS Vision features JSON")
    form.addRow("Vision features JSON", owner.people_features_json)
    advanced_toggle.toggled.connect(advanced_body.setVisible)
    layout.addWidget(advanced_body)
    manual_form = QFormLayout()
    owner.person_name = QLineEdit()
    owner.person_name.setPlaceholderText("e.g. Charles")
    manual_form.addRow("Person name", owner.person_name)
    layout.addLayout(manual_form)
    manual_actions = QHBoxLayout()
    create_person = QPushButton("Create person")
    create_person.clicked.connect(owner._create_person)
    manual_actions.addWidget(create_person)
    rename_person = QPushButton("Rename selected")
    rename_person.clicked.connect(owner._rename_person)
    manual_actions.addWidget(rename_person)
    delete_person = QPushButton("Delete selected")
    delete_person.clicked.connect(owner._delete_person)
    manual_actions.addWidget(delete_person)
    layout.addLayout(manual_actions)
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
    table.cellClicked.connect(owner._load_person_row)
    table.setSortingEnabled(True)
    tables["People"] = table
    layout.addWidget(table)
