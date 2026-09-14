"""Review queue entry point for catalog-only selection decisions."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton


def build_review_page(owner: object, layout: object) -> None:
    intro = QLabel(
        "Review is a safe catalog workflow. Pick, reject, hide, and ratings never modify original media; "
        "rejected and hidden items are excluded from the normal Library view."
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)
    owner.review_summary = QLabel("Review counts are calculated from the current catalog.")
    owner.review_summary.setObjectName("StatusSummary")
    owner.review_summary.setWordWrap(True)
    layout.addWidget(owner.review_summary)
    refresh = QPushButton("Refresh review counts")
    refresh.clicked.connect(owner._refresh_review_summary)
    layout.addWidget(refresh)
    actions = QHBoxLayout()
    owner.review_queue_buttons = {}
    for label, status in (("Needs review", "UNREVIEWED"), ("Picked", "PICKED"), ("Rejected", "REJECTED"), ("Hidden", "HIDDEN")):
        button = QPushButton(label)
        button.clicked.connect(lambda _checked=False, value=status: owner._open_review_queue(value))
        owner.review_queue_buttons[status] = button
        actions.addWidget(button)
    layout.addLayout(actions)
    all_button = QPushButton("Open all reviewable media")
    all_button.clicked.connect(lambda: owner._open_review_queue(""))
    layout.addWidget(all_button)
    owner.review_result = QLabel("Choose a queue to open it in Library.")
    owner.review_result.setWordWrap(True)
    layout.addWidget(owner.review_result)
