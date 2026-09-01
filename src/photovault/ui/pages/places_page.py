"""Places page construction for offline-safe GPS browsing."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QListWidget, QLineEdit, QFormLayout, QPushButton

from ..components import configure_tile_grid


def build_places_page(owner: object, layout: object) -> None:
    form = QFormLayout()
    radius = QLineEdit("100")
    form.addRow("Cluster radius (m)", radius)
    layout.addLayout(form)
    manual_form = QFormLayout()
    owner.place_name = QLineEdit()
    owner.place_name.setPlaceholderText("e.g. Edinburgh")
    owner.place_city = QLineEdit()
    owner.place_city.setPlaceholderText("Optional city")
    manual_form.addRow("Place name", owner.place_name)
    manual_form.addRow("City", owner.place_city)
    owner.place_id_input = QLineEdit()
    owner.place_id_input.setPlaceholderText("Select/copy a place ID to delete its catalog entry")
    manual_form.addRow("Place ID", owner.place_id_input)
    layout.addLayout(manual_form)
    create_place_button = QPushButton("Create manual place")
    create_place_button.clicked.connect(owner._create_manual_place)
    layout.addWidget(create_place_button)
    delete_place_button = QPushButton("Delete selected/manual place ID")
    delete_place_button.clicked.connect(owner._delete_manual_place)
    layout.addWidget(delete_place_button)
    button = QPushButton("Cluster GPS places")
    button.clicked.connect(lambda _checked=False, r=radius: owner._places(r))
    layout.addWidget(button)
    result = QLabel("No network geocoder is used by default.")
    result.setWordWrap(True)
    owner._results["Places"] = result
    layout.addWidget(result)
    layout.addWidget(QLabel("Browse place clusters"))
    owner.places_grid = QListWidget()
    configure_tile_grid(owner.places_grid, "PlacesGrid")
    owner.places_grid.itemClicked.connect(owner._open_place_tile)
    owner.places_grid.itemDoubleClicked.connect(owner._open_place_tile)
    owner.places_grid.addItem("No embedded GPS clusters yet")
    layout.addWidget(owner.places_grid)
