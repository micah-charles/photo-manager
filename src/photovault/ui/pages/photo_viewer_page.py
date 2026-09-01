"""Dedicated photo viewer and inspector page construction."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton


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
    toolbar.addStretch(1)
    layout.addLayout(toolbar)

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
