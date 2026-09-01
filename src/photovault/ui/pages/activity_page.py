"""Activity page construction kept separate from global window coordination."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QListWidget,
    QLineEdit,
    QPushButton,
    QTableWidget,
)


def build_activity_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    """Build the user-facing activity feed and its advanced audit table."""
    owner.activity_summary = QLabel("Recent library, backup, verification, and storage activity.")
    owner.activity_summary.setObjectName("StatusSummary")
    owner.activity_summary.setWordWrap(True)
    layout.addWidget(owner.activity_summary)

    form = QFormLayout()
    owner.undo_operation_id = QLineEdit()
    form.addRow("Quarantine operation ID", owner.undo_operation_id)
    layout.addLayout(form)

    undo_button = QPushButton("Undo completed quarantine")
    undo_button.clicked.connect(owner._undo_quarantine)
    layout.addWidget(undo_button)

    owner.undo_result = QLabel("Undo re-hashes the quarantined file and never overwrites a conflicting original.")
    owner.undo_result.setWordWrap(True)
    layout.addWidget(owner.undo_result)

    layout.addWidget(QLabel("Recent activity"))
    owner.activity_feed = QListWidget()
    owner.activity_feed.setObjectName("ActivityFeed")
    owner.activity_feed.setMaximumHeight(220)
    owner.activity_feed.addItem("No activity recorded yet")
    layout.addWidget(owner.activity_feed)

    table = QTableWidget()
    table.setSortingEnabled(True)
    tables["Operations"] = table
    layout.addWidget(table)
