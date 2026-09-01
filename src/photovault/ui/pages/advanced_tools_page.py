"""Advanced tools landing page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton


def build_advanced_tools_page(owner: object, layout: object) -> None:
    intro = QLabel(
        "Power tools remain available for inspection and recovery. These actions use the existing safety services; nothing runs until you explicitly choose a tool."
    )
    intro.setObjectName("StatusSummary")
    intro.setWordWrap(True)
    layout.addWidget(intro)
    for button_text, target in (
        ("Scan a library folder", "Scan"), ("Build a copy plan", "Copy Plans"),
        ("Review Backup Health", "Backup Health"), ("Open Catalog Recovery", "Catalog Recovery"),
        ("Open Quarantine", "Quarantine"),
    ):
        button = QPushButton(button_text)
        button.clicked.connect(lambda _checked=False, page=target: owner._select_page(page))
        layout.addWidget(button)
