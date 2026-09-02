"""Categories/AI analysis page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QLabel, QPushButton, QTableWidget

from ..components import PhotoGrid


def build_categories_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    owner.categories_result = QLabel(
        "Categories are derived from local analysis and open the same photo-first Library view. They are advisory metadata and never change original files."
    )
    owner.categories_result.setWordWrap(True)
    layout.addWidget(owner.categories_result)
    analysis_actions = QHBoxLayout()
    settings_button = QPushButton("Configure analysis in Settings")
    settings_button.clicked.connect(lambda: owner._select_page("Settings"))
    analysis_actions.addWidget(settings_button)
    layout.addLayout(analysis_actions)
    actions = QHBoxLayout()
    refresh_button = QPushButton("Refresh categories")
    refresh_button.clicked.connect(owner._refresh_categories)
    actions.addWidget(refresh_button)
    open_button = QPushButton("Open selected category")
    open_button.clicked.connect(owner._open_selected_category)
    actions.addWidget(open_button)
    accept_button = QPushButton("Accept category as Tag")
    accept_button.setToolTip("Copy the current advisory category into a user tag; the AI category remains separate.")
    accept_button.clicked.connect(owner._accept_selected_category)
    actions.addWidget(accept_button)
    layout.addLayout(actions)
    layout.addWidget(QLabel("Browse categories"))
    owner.category_grid = PhotoGrid(
        object_name="CategoryGrid", icon_size=(150, 100), grid_size=(190, 140), multi_select=False,
    )
    owner.category_grid.itemClicked.connect(owner._open_category_tile)
    owner.category_grid.itemDoubleClicked.connect(owner._open_category_tile)
    owner.category_grid.itemActivated.connect(owner._open_category_tile)
    owner.category_grid.show_empty_state("No categories indexed yet")
    layout.addWidget(owner.category_grid)
    table = QTableWidget()
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.cellDoubleClicked.connect(owner._open_category_row)
    tables["Categories"] = table
    layout.addWidget(table)
