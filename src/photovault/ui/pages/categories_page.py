"""Categories/AI analysis page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QProgressBar, QTableWidget

from ..components import PhotoGrid


def build_categories_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    owner.categories_result = QLabel(
        "Categories are derived from local analysis and open the same photo-first Library view. They are advisory metadata and never change original files."
    )
    owner.categories_result.setWordWrap(True)
    layout.addWidget(owner.categories_result)
    analysis_form = QFormLayout()
    owner.category_model_path = QLineEdit()
    owner.category_model_path.setPlaceholderText("Path to local ONNX model (stored outside Git)")
    owner.category_labels_path = QLineEdit()
    owner.category_labels_path.setPlaceholderText("Path to matching labels.txt")
    owner.category_limit = QLineEdit("0")
    owner.category_top_k = QLineEdit("5")
    analysis_form.addRow("ONNX model", owner.category_model_path)
    analysis_form.addRow("Labels", owner.category_labels_path)
    analysis_form.addRow("Limit (0 = all)", owner.category_limit)
    analysis_form.addRow("Top labels", owner.category_top_k)
    layout.addLayout(analysis_form)
    analysis_actions = QHBoxLayout()
    owner.category_start_button = QPushButton("Run local category analysis")
    owner.category_start_button.clicked.connect(owner._start_category_analysis)
    analysis_actions.addWidget(owner.category_start_button)
    owner.category_cancel_button = QPushButton("Cancel analysis")
    owner.category_cancel_button.setEnabled(False)
    owner.category_cancel_button.clicked.connect(owner._cancel_category_analysis)
    analysis_actions.addWidget(owner.category_cancel_button)
    layout.addLayout(analysis_actions)
    owner.category_progress = QProgressBar()
    owner.category_progress.setRange(0, 100)
    owner.category_progress.setValue(0)
    owner.category_progress.setFormat("Ready")
    layout.addWidget(owner.category_progress)
    actions = QHBoxLayout()
    refresh_button = QPushButton("Refresh categories")
    refresh_button.clicked.connect(owner._refresh_categories)
    actions.addWidget(refresh_button)
    open_button = QPushButton("Open selected category")
    open_button.clicked.connect(owner._open_selected_category)
    actions.addWidget(open_button)
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
