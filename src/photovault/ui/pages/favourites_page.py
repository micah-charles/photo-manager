"""Favourites page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QPushButton, QTableWidget


def build_favourites_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    form = QFormLayout()
    owner.favourite_asset_id = QLineEdit()
    owner.favourite_note = QLineEdit()
    owner.favourite_legacy_manifest = QLineEdit()
    form.addRow("Catalog asset ID", owner.favourite_asset_id)
    form.addRow("Note (optional)", owner.favourite_note)
    form.addRow("Legacy favorites.json (optional)", owner.favourite_legacy_manifest)
    layout.addLayout(form)
    favourite_button = QPushButton("Add / update favourite")
    favourite_button.clicked.connect(owner._set_favourite)
    layout.addWidget(favourite_button)
    remove_button = QPushButton("Remove selected asset ID from favourites")
    remove_button.clicked.connect(owner._remove_favourite)
    layout.addWidget(remove_button)
    import_button = QPushButton("Import legacy gallery favourites JSON")
    import_button.clicked.connect(owner._import_legacy_favourites)
    layout.addWidget(import_button)
    browse_button = QPushButton("Browse favourites in Library")
    browse_button.clicked.connect(owner._browse_favourites)
    layout.addWidget(browse_button)
    owner.favourite_result = QLabel("Favourites are catalog annotations only; originals and backup verification are unchanged.")
    owner.favourite_result.setWordWrap(True)
    layout.addWidget(owner.favourite_result)
    table = QTableWidget()
    table.setSortingEnabled(True)
    tables["Favourites"] = table
    layout.addWidget(table)
