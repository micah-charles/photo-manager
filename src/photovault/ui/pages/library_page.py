"""Photo-first Library page construction."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)


def build_library_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    """Build the visual library while leaving query and safety policy to owner."""
    form = QFormLayout()
    owner.library_search = QLineEdit()
    owner.library_folder = QLineEdit()
    owner.library_media_type = QComboBox()
    owner.library_media_type.addItems(["ALL", "IMAGE", "VIDEO"])
    owner.library_sort = QComboBox()
    owner.library_sort.addItem("Capture date — newest", "captured_desc")
    owner.library_sort.addItem("Capture date — oldest", "captured_asc")
    owner.library_sort.addItem("Filename", "name_asc")
    owner.library_sort.addItem("Largest first", "size_desc")
    owner.library_favourites_only = QCheckBox("Favourites only")
    owner.library_limit = QLineEdit("200")
    form.addRow("Search filename / path", owner.library_search)
    form.addRow("Folder prefix", owner.library_folder)
    form.addRow("Media", owner.library_media_type)
    form.addRow("Sort", owner.library_sort)
    form.addRow("Filter", owner.library_favourites_only)
    form.addRow("Page size", owner.library_limit)
    layout.addLayout(form)

    owner.library_collection_result = QLabel("All catalogued media")
    owner.library_collection_result.setWordWrap(True)
    layout.addWidget(owner.library_collection_result)
    refresh_button = QPushButton("Refresh catalog library")
    refresh_button.clicked.connect(owner._refresh_library)
    layout.addWidget(refresh_button)
    clear_collection_button = QPushButton("Clear collection filter")
    clear_collection_button.clicked.connect(owner._clear_library_collection)
    layout.addWidget(clear_collection_button)
    favourite_button = QPushButton("Toggle favourite for selected item(s)")
    favourite_button.clicked.connect(owner._toggle_selected_library_favourites)
    layout.addWidget(favourite_button)

    collection_actions = QHBoxLayout()
    owner.library_collection_target = QComboBox()
    owner.library_collection_target.addItem("Select an album…", None)
    collection_actions.addWidget(owner.library_collection_target, 1)
    add_collection_button = QPushButton("Add selected to album")
    add_collection_button.clicked.connect(owner._add_selected_to_collection)
    collection_actions.addWidget(add_collection_button)
    layout.addLayout(collection_actions)

    owner.library_result = QLabel("Catalog-backed results remain visible when an original volume is offline.")
    owner.library_result.setWordWrap(True)
    layout.addWidget(owner.library_result)
    owner.library_selection_count = QLabel("0 selected")
    layout.addWidget(owner.library_selection_count)
    owner.library_technical_toggle = QCheckBox("Show advanced catalog details")
    owner.library_technical_toggle.setChecked(False)
    owner.library_technical_toggle.toggled.connect(owner._set_library_technical_visible)
    layout.addWidget(owner.library_technical_toggle)

    browser_layout = QHBoxLayout()
    owner.library_grid = QListWidget()
    owner.library_grid.setViewMode(QListWidget.ViewMode.IconMode)
    owner.library_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
    owner.library_grid.setIconSize(QSize(160, 120))
    owner.library_grid.setGridSize(QSize(190, 170))
    owner.library_grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    owner.library_grid.itemSelectionChanged.connect(owner._library_selection_changed)
    owner.library_grid.itemDoubleClicked.connect(owner._open_library_item)
    owner.library_grid.addItem("No photos indexed yet")
    browser_layout.addWidget(owner.library_grid, 3)

    preview_layout = QVBoxLayout()
    owner.library_preview = QLabel("Select a catalogued item to preview its cached thumbnail.")
    owner.library_preview.setWordWrap(True)
    owner.library_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    owner.library_preview.setMinimumSize(260, 220)
    preview_layout.addWidget(owner.library_preview)
    owner.library_preview_details = QLabel("Original availability appears here.")
    owner.library_preview_details.setWordWrap(True)
    preview_layout.addWidget(owner.library_preview_details)
    browser_layout.addLayout(preview_layout, 2)
    layout.addLayout(browser_layout)

    table = QTableWidget()
    table.setSortingEnabled(True)
    table.setVisible(False)
    tables["Library"] = table
    layout.addWidget(table)
