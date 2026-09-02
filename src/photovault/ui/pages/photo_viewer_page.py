"""Dedicated photo viewer and inspector page construction."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton


def build_photo_viewer_page(owner: object, layout: object) -> None:
    """Build the cached-preview viewer; owner controls item loading and navigation."""
    toolbar = QHBoxLayout()
    back_button = QPushButton("Back to Library")
    back_button.clicked.connect(lambda: owner._select_page("Library"))
    toolbar.addWidget(back_button)
    owner.viewer_previous = QPushButton("Previous")
    owner.viewer_previous.clicked.connect(lambda: owner._show_viewer_item(owner._viewer_index - 1))
    toolbar.addWidget(owner.viewer_previous)
    owner.viewer_next = QPushButton("Next")
    owner.viewer_next.clicked.connect(lambda: owner._show_viewer_item(owner._viewer_index + 1))
    toolbar.addWidget(owner.viewer_next)
    toolbar.addWidget(QLabel("Review:"))
    owner.viewer_review_action = QComboBox()
    owner.viewer_review_action.addItem("Pick", "PICKED")
    owner.viewer_review_action.addItem("Reject", "REJECTED")
    owner.viewer_review_action.addItem("Hide", "HIDDEN")
    owner.viewer_review_action.addItem("Unreviewed", "UNREVIEWED")
    toolbar.addWidget(owner.viewer_review_action)
    review_button = QPushButton("Apply")
    review_button.clicked.connect(owner._apply_viewer_review)
    toolbar.addWidget(review_button)
    owner.viewer_rating_action = QComboBox()
    owner.viewer_rating_action.addItem("Clear rating", 0)
    for rating in range(1, 6):
        owner.viewer_rating_action.addItem(f"{rating}★", rating)
    toolbar.addWidget(owner.viewer_rating_action)
    rate_button = QPushButton("Rate")
    rate_button.clicked.connect(owner._apply_viewer_rating)
    toolbar.addWidget(rate_button)
    toolbar.addStretch(1)
    layout.addLayout(toolbar)

    shortcuts = QLabel("Keyboard: ←/→ navigate · P pick · X/R reject · H hide · F favourite · 0–5 rating")
    shortcuts.setObjectName("StatusSummary")
    layout.addWidget(shortcuts)

    viewer_body = QHBoxLayout()
    owner.viewer_image = QLabel("Open a photo from Library to view it here.")
    owner.viewer_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
    owner.viewer_image.setMinimumSize(640, 480)
    owner.viewer_image.setWordWrap(True)
    viewer_body.addWidget(owner.viewer_image, 3)
    owner.viewer_details = QLabel("Photo details appear here.")
    owner.viewer_details.setWordWrap(True)
    owner.viewer_details.setMinimumWidth(280)
    viewer_body.addWidget(owner.viewer_details, 1)
    layout.addLayout(viewer_body)
