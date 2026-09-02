"""Settings landing page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QSpinBox


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
    ai_heading = QLabel("AI & Intelligence")
    ai_heading.setObjectName("SectionHeading")
    layout.addWidget(ai_heading)
    ai_help = QLabel(
        "Optional local analysis runs in a background worker. Model output is advisory and remains separate from user Tags."
    )
    ai_help.setWordWrap(True)
    layout.addWidget(ai_help)
    ai_form = QFormLayout()
    owner.category_model_path = QLineEdit()
    owner.category_model_path.setPlaceholderText("Path to local ONNX model (stored outside Git)")
    owner.category_labels_path = QLineEdit()
    owner.category_labels_path.setPlaceholderText("Path to matching labels.txt")
    owner.category_limit = QSpinBox()
    owner.category_limit.setRange(0, 10_000_000)
    owner.category_limit.setSpecialValueText("All images")
    owner.category_top_k = QSpinBox()
    owner.category_top_k.setRange(1, 100)
    owner.category_top_k.setValue(5)
    ai_form.addRow("Category model", owner.category_model_path)
    ai_form.addRow("Category labels", owner.category_labels_path)
    ai_form.addRow("Analysis limit", owner.category_limit)
    ai_form.addRow("Top labels", owner.category_top_k)
    layout.addLayout(ai_form)
    ai_actions = QHBoxLayout()
    owner.category_start_button = QPushButton("Run category analysis")
    owner.category_start_button.clicked.connect(owner._start_category_analysis)
    ai_actions.addWidget(owner.category_start_button)
    owner.category_cancel_button = QPushButton("Cancel analysis")
    owner.category_cancel_button.setEnabled(False)
    owner.category_cancel_button.clicked.connect(owner._cancel_category_analysis)
    ai_actions.addWidget(owner.category_cancel_button)
    open_categories = QPushButton("Open Categories")
    open_categories.clicked.connect(lambda: owner._select_page("Categories"))
    ai_actions.addWidget(open_categories)
    layout.addLayout(ai_actions)
    owner.category_progress = QProgressBar()
    owner.category_progress.setRange(0, 100)
    owner.category_progress.setValue(0)
    owner.category_progress.setFormat("Ready")
    layout.addWidget(owner.category_progress)
    for button_text, target in (("Open Advanced Tools", "Advanced Tools"), ("Open Catalog Recovery", "Catalog Recovery")):
        button = QPushButton(button_text)
        button.clicked.connect(lambda _checked=False, page=target: owner._select_page(page))
        layout.addWidget(button)
