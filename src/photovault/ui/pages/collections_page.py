"""Collections and user-album page construction."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTableWidget,
)

from ..components import configure_tile_grid


def build_collections_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    """Build visual collection entry points while leaving catalog work to owner."""
    owner.collections_result = QLabel(
        "Catalog-derived browse views: date, folders, favourites, embedded-GPS places, and advisory visual groups. No media files are changed."
    )
    owner.collections_result.setWordWrap(True)
    layout.addWidget(owner.collections_result)

    refresh_button = QPushButton("Refresh collections")
    refresh_button.clicked.connect(owner._refresh_collections)
    layout.addWidget(refresh_button)
    open_button = QPushButton("Open selected collection in Library")
    open_button.clicked.connect(owner._open_selected_collection)
    layout.addWidget(open_button)

    create_actions = QHBoxLayout()
    owner.new_collection_title = QLineEdit()
    owner.new_collection_title.setPlaceholderText("New album name")
    create_actions.addWidget(owner.new_collection_title, 1)
    create_button = QPushButton("Create album")
    create_button.clicked.connect(owner._create_user_collection)
    create_actions.addWidget(create_button)
    layout.addLayout(create_actions)

    layout.addWidget(QLabel("Browse collections · single-click to select, double-click or press Enter to open"))
    owner.collections_grid = QListWidget()
    configure_tile_grid(owner.collections_grid, "CollectionGrid")
    # Keep the first click as selection. Opening on itemClicked makes a
    # double-click unreliable: the first click navigates away, so the second
    # click no longer reaches this card. Double-click and keyboard activation
    # are the explicit open actions; the button above handles single-click
    # users.
    owner.collections_grid.itemDoubleClicked.connect(owner._open_collection_tile)
    owner.collections_grid.itemActivated.connect(owner._open_collection_tile)
    layout.addWidget(owner.collections_grid)

    layout.addWidget(QLabel("Your albums · single-click to select, double-click or press Enter to open"))
    owner.collections_album_grid = QListWidget()
    configure_tile_grid(owner.collections_album_grid, "AlbumGrid", icon_size=(150, 110), grid_size=(190, 155))
    owner.collections_album_grid.itemDoubleClicked.connect(owner._open_album_tile)
    owner.collections_album_grid.itemActivated.connect(owner._open_album_tile)
    layout.addWidget(owner.collections_album_grid)

    table = QTableWidget()
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.cellDoubleClicked.connect(owner._open_collection_row)
    tables["Collections"] = table
    layout.addWidget(table)
    owner.collections_technical_toggle = QCheckBox("Show advanced collection details")
    owner.collections_technical_toggle.toggled.connect(owner._set_collections_technical_visible)
    table.setVisible(False)
    layout.addWidget(owner.collections_technical_toggle)
