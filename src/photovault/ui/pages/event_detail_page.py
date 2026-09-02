"""Contextual Event detail view for catalog-only event organisation."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QListWidget, QPushButton

from ..components import configure_tile_grid


def build_event_detail_page(owner: object, layout: object) -> None:
    owner.event_detail_summary = QLabel("Select an event from Events to view its details.")
    owner.event_detail_summary.setObjectName("StatusSummary")
    owner.event_detail_summary.setWordWrap(True)
    layout.addWidget(owner.event_detail_summary)

    actions = QHBoxLayout()
    back = QPushButton("Back to Events")
    back.clicked.connect(lambda: owner._select_page("Events"))
    actions.addWidget(back)
    open_library = QPushButton("Open all in Library")
    open_library.clicked.connect(owner._open_event_detail_in_library)
    actions.addWidget(open_library)
    edit = QPushButton("Edit Event")
    edit.clicked.connect(owner._edit_event_from_detail)
    actions.addWidget(edit)
    remove = QPushButton("Remove selected from Event")
    remove.clicked.connect(owner._remove_event_detail_selection)
    actions.addWidget(remove)
    layout.addLayout(actions)

    owner.event_detail_result = QLabel(
        "Removing an item only removes the Event membership; the original file and catalog asset remain safe."
    )
    owner.event_detail_result.setWordWrap(True)
    layout.addWidget(owner.event_detail_result)
    owner.event_detail_source_filter = QComboBox()
    owner.event_detail_source_filter.setAccessibleName("Event detail source filter")
    owner.event_detail_source_filter.addItem("All sources", None)
    owner.event_detail_source_filter.currentIndexChanged.connect(owner._refresh_event_detail)
    layout.addWidget(owner.event_detail_source_filter)
    owner.event_detail_grid = QListWidget()
    configure_tile_grid(owner.event_detail_grid, "EventDetailGrid", icon_size=(170, 130), grid_size=(205, 165))
    owner.event_detail_grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    owner.event_detail_grid.setAccessibleName("Event detail photo grid")
    owner.event_detail_grid.itemDoubleClicked.connect(owner._open_event_detail_item)
    layout.addWidget(owner.event_detail_grid, 1)
