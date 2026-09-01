"""Home/Dashboard page construction."""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QPushButton, QTableWidget, QVBoxLayout, QWidget


def build_home_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    owner.dashboard_result = QLabel("Loading catalog health…")
    owner.dashboard_result.setWordWrap(True)
    layout.addWidget(owner.dashboard_result)
    owner.dashboard_cards = {}
    cards = QHBoxLayout()
    for card_name, card_title in (
        ("safety", "Backup status"), ("library", "Your library"),
        ("storage", "Storage"), ("activity", "Recent activity"),
    ):
        card = QWidget()
        card.setStyleSheet("QWidget { background: white; border: 1px solid #dfe3eb; border-radius: 10px; padding: 10px; }")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        heading = QLabel(card_title)
        heading.setStyleSheet("font-weight: 600; color: #647084; background: transparent; border: 0;")
        value = QLabel("Loading…")
        value.setWordWrap(True)
        value.setStyleSheet("font-size: 15px; font-weight: 700; background: transparent; border: 0;")
        card_layout.addWidget(heading)
        card_layout.addWidget(value)
        owner.dashboard_cards[card_name] = value
        cards.addWidget(card)
    layout.addLayout(cards)

    quick_actions = QHBoxLayout()
    for action_name, target in (
        ("Backup now", "Android Devices"), ("Browse Library", "Library"),
        ("View People", "People"), ("View Places", "Places"),
    ):
        action = QPushButton(action_name)
        action.clicked.connect(lambda _checked=False, page=target: owner._select_page(page))
        quick_actions.addWidget(action)
    layout.addLayout(quick_actions)
    layout.addWidget(QLabel("Recent photos"))
    owner.dashboard_recent_grid = QListWidget()
    owner.dashboard_recent_grid.setObjectName("RecentPhotoGrid")
    owner.dashboard_recent_grid.setViewMode(QListWidget.ViewMode.IconMode)
    owner.dashboard_recent_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
    owner.dashboard_recent_grid.setIconSize(QSize(120, 90))
    owner.dashboard_recent_grid.setGridSize(QSize(150, 125))
    owner.dashboard_recent_grid.itemDoubleClicked.connect(owner._open_dashboard_item)
    layout.addWidget(owner.dashboard_recent_grid)
    dashboard_table = QTableWidget()
    tables["Dashboard"] = dashboard_table
    layout.addWidget(dashboard_table)
    button = QPushButton("Refresh dashboard")
    button.clicked.connect(owner._refresh_dashboard)
    layout.addWidget(button)
