"""Event management page for logical, catalog-only grouping."""
from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QPushButton, QTableWidget


def build_events_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    intro = QLabel("Events group media logically. Creating an event never moves or rewrites original files.")
    intro.setWordWrap(True)
    layout.addWidget(intro)
    form = QFormLayout()
    owner.event_name = QLineEdit()
    owner.event_name.setPlaceholderText("e.g. Edinburgh trip")
    owner.event_start = QLineEdit()
    owner.event_start.setPlaceholderText("YYYY-MM-DD (optional)")
    owner.event_end = QLineEdit()
    owner.event_end.setPlaceholderText("YYYY-MM-DD (optional)")
    form.addRow("Event name", owner.event_name)
    form.addRow("Start date", owner.event_start)
    form.addRow("End date", owner.event_end)
    layout.addLayout(form)
    create = QPushButton("Create event")
    create.clicked.connect(owner._create_event)
    layout.addWidget(create)
    refresh = QPushButton("Refresh events")
    refresh.clicked.connect(owner._refresh_events)
    layout.addWidget(refresh)
    owner.events_result = QLabel("Events are catalog metadata.")
    owner.events_result.setWordWrap(True)
    layout.addWidget(owner.events_result)
    table = QTableWidget()
    table.cellDoubleClicked.connect(owner._open_event_row)
    tables["Events"] = table
    layout.addWidget(table)
