"""Settings landing page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton


def build_settings_page(owner: object, layout: object) -> None:
    intro = QLabel(
        "PhotoVault keeps backup truth separate from photo enrichment. Use the links below to reach catalog, backup, and intelligence controls."
    )
    intro.setObjectName("StatusSummary")
    intro.setWordWrap(True)
    layout.addWidget(intro)
    sections = (
        ("Library and privacy", "Photos remain local; thumbnails and enrichment are rebuildable catalog data."),
        ("Backup defaults", "Verified copies, atomic destination writes, and stable drive identity remain the safety defaults."),
        ("AI & Intelligence", "Category, people, place, and duplicate analysis are optional and never modify originals."),
    )
    for heading, description in sections:
        card = QLabel(f"{heading}\n{description}")
        card.setWordWrap(True)
        card.setObjectName("SettingsCard")
        layout.addWidget(card)
    for button_text, target in (("Open Advanced Tools", "Advanced Tools"), ("Open Catalog Recovery", "Catalog Recovery")):
        button = QPushButton(button_text)
        button.clicked.connect(lambda _checked=False, page=target: owner._select_page(page))
        layout.addWidget(button)
