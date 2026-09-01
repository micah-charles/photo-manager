"""Home/Dashboard page construction."""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QTableWidget, QVBoxLayout, QWidget

from ..components import PhotoGrid


def build_home_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    owner.dashboard_result = QLabel("Loading catalog health…")
    owner.dashboard_result.setWordWrap(True)
    layout.addWidget(owner.dashboard_result)
    owner.dashboard_cards = {}
    cards = QHBoxLayout()
    for card_name, card_title in (
        ("safety", "Backup status"), ("library", "Your library"),
        ("storage", "Storage"), ("android", "Android phone"),
        ("activity", "Recent activity"),
    ):
        card = QWidget()
        card.setObjectName("DashboardCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        heading = QLabel(card_title)
        heading.setObjectName("DashboardCardHeading")
        value = QLabel("Loading…")
        value.setWordWrap(True)
        value.setObjectName("DashboardCardValue")
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
    preview_actions = QHBoxLayout()
    owner.dashboard_thumbnail_button = QPushButton("Build missing previews")
    owner.dashboard_thumbnail_button.setToolTip("Create rebuildable previews beside the catalog; originals are read-only.")
    owner.dashboard_thumbnail_button.clicked.connect(owner._start_thumbnail_generation)
    preview_actions.addWidget(owner.dashboard_thumbnail_button)
    owner.dashboard_thumbnail_status = QLabel("Preview cache status: use Build missing previews if cards have no images.")
    owner.dashboard_thumbnail_status.setWordWrap(True)
    preview_actions.addWidget(owner.dashboard_thumbnail_status, 1)
    layout.addLayout(preview_actions)
    owner.dashboard_recent_grid = PhotoGrid(
        object_name="RecentPhotoGrid", icon_size=(120, 90), grid_size=(150, 125), multi_select=False,
    )
    owner.dashboard_recent_grid.itemDoubleClicked.connect(owner._open_dashboard_item)
    layout.addWidget(owner.dashboard_recent_grid)
    dashboard_table = QTableWidget()
    dashboard_table.setVisible(False)
    tables["Dashboard"] = dashboard_table
    layout.addWidget(dashboard_table)
    owner.dashboard_technical_toggle = QCheckBox("Show advanced catalog details")
    owner.dashboard_technical_toggle.toggled.connect(owner._set_dashboard_technical_visible)
    layout.addWidget(owner.dashboard_technical_toggle)
    button = QPushButton("Refresh dashboard")
    button.clicked.connect(owner._refresh_dashboard)
    layout.addWidget(button)
