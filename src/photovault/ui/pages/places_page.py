"""Places page construction for offline-safe GPS browsing."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QListWidget, QLineEdit, QFormLayout, QPushButton

from ..components import configure_tile_grid


def build_places_page(owner: object, layout: object) -> None:
    form = QFormLayout()
    radius = QLineEdit("100")
    form.addRow("Cluster radius (m)", radius)
    layout.addLayout(form)
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
    owner.places_grid.itemDoubleClicked.connect(owner._open_place_tile)
    owner.places_grid.addItem("No embedded GPS clusters yet")
    layout.addWidget(owner.places_grid)
