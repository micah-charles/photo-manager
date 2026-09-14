"""Chronological, photo-first Library page construction."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPushButton, QScrollArea, QToolButton, QTableWidget, QVBoxLayout, QWidget,
)

from ..components import PhotoGrid


def _make_filter_controls(owner: object, layout: QVBoxLayout) -> None:
    """Keep catalog filters available without permanently cluttering Library."""
    row = QHBoxLayout()
    owner.library_folder = QLineEdit()
    owner.library_folder.setAccessibleName("Filter by folder")
    owner.library_folder.setPlaceholderText("Folder prefix")
    row.addWidget(owner.library_folder, 2)
    owner.library_media_type = QComboBox()
    owner.library_media_type.setAccessibleName("Media type filter")
    owner.library_media_type.addItems(["ALL", "IMAGE", "VIDEO"])
    row.addWidget(owner.library_media_type)
    owner.library_sort = QComboBox()
    owner.library_sort.setAccessibleName("Sort library")
    for label, value in (("Capture date — newest", "captured_desc"), ("Capture date — oldest", "captured_asc"), ("Filename", "name_asc"), ("Largest first", "size_desc")):
        owner.library_sort.addItem(label, value)
    row.addWidget(owner.library_sort, 2)
    owner.library_favourites_only = QCheckBox("Favourites only")
    row.addWidget(owner.library_favourites_only)
    layout.addLayout(row)
    organisation = QHBoxLayout()
    for name, label, tip, width in (
        ("library_source_filter", "Any source", "Source provenance", 150),
        ("library_event_filter", "Any event", "Topic / event", 150),
        ("library_tag_filter", "Any tag", "Tag", 130),
        ("library_place_filter", "Any place", "Manual or embedded place", 130),
        ("library_person_filter", "Any person", "Person", 130),
        ("library_category_filter", "Any category", "AI-derived category; user Tags remain separate", 140),
    ):
        combo = QComboBox()
        combo.setAccessibleName(label)
        combo.setMinimumWidth(width)
        combo.setToolTip(tip)
        combo.addItem(label, None)
        setattr(owner, name, combo)
        organisation.addWidget(combo)
    owner.library_review_filter = QComboBox()
    owner.library_review_filter.setAccessibleName("Review filter")
    for label, value in (("Any review status", ""), ("Unreviewed", "UNREVIEWED"), ("Picked", "PICKED"), ("Rejected", "REJECTED"), ("Hidden", "HIDDEN")):
        owner.library_review_filter.addItem(label, value)
    organisation.addWidget(owner.library_review_filter)
    owner.library_rating_filter = QComboBox()
    owner.library_rating_filter.setAccessibleName("Rating filter")
    owner.library_rating_filter.addItem("Any rating", None)
    for rating in range(1, 6):
        owner.library_rating_filter.addItem(f"{rating}+ stars", rating)
    organisation.addWidget(owner.library_rating_filter)
    owner.library_include_rejected = QCheckBox("Include rejected/hidden")
    organisation.addWidget(owner.library_include_rejected)
    clear = QPushButton("Clear filters")
    clear.setToolTip("Clear organisation filters")
    clear.clicked.connect(owner._clear_library_organisation_filters)
    organisation.addWidget(clear)
    layout.addLayout(organisation)
    for combo in (owner.library_source_filter, owner.library_event_filter, owner.library_tag_filter,
                  owner.library_place_filter, owner.library_person_filter, owner.library_category_filter,
                  owner.library_review_filter, owner.library_rating_filter):
        combo.currentIndexChanged.connect(owner._reset_library_page)
    owner.library_include_rejected.toggled.connect(owner._reset_library_page)


def _make_actions(owner: object, layout: QVBoxLayout) -> None:
    """Show bulk actions only after selection."""
    owner.library_action_panel = QWidget()
    actions = QHBoxLayout(owner.library_action_panel)
    actions.setContentsMargins(0, 0, 0, 0)
    owner.library_selection_count = QLabel("0 selected")
    actions.addWidget(owner.library_selection_count)
    owner.library_collection_target = QComboBox()
    owner.library_collection_target.setAccessibleName("Add selected to topic")
    owner.library_collection_target.addItem("Add to Topic…", None)
    actions.addWidget(owner.library_collection_target)
    add = QPushButton("Add to Topic")
    add.clicked.connect(owner._add_selected_to_collection)
    actions.addWidget(add)
    owner.library_review_action = QComboBox()
    owner.library_review_action.setAccessibleName("Review action")
    for label, value in (("Pick", "PICKED"), ("Reject", "REJECTED"), ("Hide", "HIDDEN"), ("Mark unreviewed", "UNREVIEWED")):
        owner.library_review_action.addItem(label, value)
    actions.addWidget(owner.library_review_action)
    review = QPushButton("Apply")
    review.clicked.connect(owner._apply_selected_review)
    actions.addWidget(review)
    favourite = QPushButton("Favourite")
    favourite.clicked.connect(owner._toggle_selected_library_favourites)
    actions.addWidget(favourite)
    owner.library_rating_action = QComboBox()
    owner.library_rating_action.setAccessibleName("Rating action")
    owner.library_rating_action.addItem("Rate…", None)
    for rating in range(1, 6):
        owner.library_rating_action.addItem(f"{rating}★", rating)
    actions.addWidget(owner.library_rating_action)
    rate = QPushButton("Rate")
    rate.clicked.connect(owner._apply_selected_rating)
    actions.addWidget(rate)
    topic = QPushButton("Create Topic")
    topic.setToolTip("Create a Topic/Event from the selected photos")
    topic.clicked.connect(owner._create_topic_from_selection)
    actions.addWidget(topic)
    actions.addStretch(1)
    owner.library_action_panel.setVisible(False)
    layout.addWidget(owner.library_action_panel)


def build_library_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    """Build the Timeline-first Library described by the product mockup."""
    header = QHBoxLayout()
    owner.library_search = QLineEdit()
    owner.library_search.setAccessibleName("Search library")
    owner.library_search.setPlaceholderText("Search photos, topics, places…")
    owner.library_search.textChanged.connect(owner._reset_library_page)
    header.addWidget(owner.library_search, 1)
    owner.library_filter_button = QToolButton()
    owner.library_filter_button.setText("Filter")
    owner.library_filter_button.setCheckable(True)
    owner.library_filter_button.setAccessibleName("Open library filters")
    header.addWidget(owner.library_filter_button)
    owner.library_sort_button = QToolButton()
    owner.library_sort_button.setText("Sort")
    owner.library_sort_button.setAccessibleName("Sort timeline")
    owner.library_sort_button.clicked.connect(owner._show_library_sort_menu)
    header.addWidget(owner.library_sort_button)
    owner.library_recent_button = QPushButton("Recently Added")
    owner.library_recent_button.setCheckable(True)
    owner.library_recent_button.setToolTip("Show media catalogued or imported during the last 30 days")
    owner.library_recent_button.toggled.connect(owner._toggle_recently_added)
    header.addWidget(owner.library_recent_button)
    refresh = QPushButton("Refresh")
    refresh.clicked.connect(owner._refresh_library)
    header.addWidget(refresh)
    layout.addLayout(header)

    owner.library_filter_panel = QWidget()
    filter_layout = QVBoxLayout(owner.library_filter_panel)
    filter_layout.setContentsMargins(0, 0, 0, 0)
    _make_filter_controls(owner, filter_layout)
    owner.library_filter_panel.setVisible(False)
    owner.library_filter_button.toggled.connect(owner.library_filter_panel.setVisible)
    layout.addWidget(owner.library_filter_panel)
    _make_actions(owner, layout)

    owner.library_collection_result = QLabel("Timeline · all sources merged")
    owner.library_collection_result.setObjectName("StatusSummary")
    layout.addWidget(owner.library_collection_result)
    browser = QHBoxLayout()
    owner.library_months = QListWidget()
    owner.library_months.setAccessibleName("Timeline month navigation")
    owner.library_months.setMaximumWidth(170)
    owner.library_months.currentRowChanged.connect(owner._library_month_changed)
    browser.addWidget(owner.library_months)
    owner.library_timeline_scroll = QScrollArea()
    owner.library_timeline_scroll.setWidgetResizable(True)
    owner.library_timeline_content = QWidget()
    owner.library_timeline_layout = QVBoxLayout(owner.library_timeline_content)
    owner.library_timeline_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    owner.library_timeline_scroll.setWidget(owner.library_timeline_content)
    browser.addWidget(owner.library_timeline_scroll, 5)
    inspector = QVBoxLayout()
    owner.library_preview = QLabel("Select a photo to inspect")
    owner.library_preview.setAccessibleName("Selected photo preview")
    owner.library_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    owner.library_preview.setMinimumSize(260, 220)
    inspector.addWidget(owner.library_preview, 1)
    owner.library_preview_details = QLabel("Metadata, organisation and backup status appear here.")
    owner.library_preview_details.setAccessibleName("Photo inspector")
    owner.library_preview_details.setWordWrap(True)
    owner.library_preview_details.setMinimumWidth(260)
    inspector.addWidget(owner.library_preview_details)
    browser.addLayout(inspector, 2)
    layout.addLayout(browser, 1)

    # Hidden aggregate grid preserves existing controller/test APIs. Visible grids are per day.
    owner.library_grid = PhotoGrid(object_name="PhotoGrid")
    owner.library_grid.setAccessibleName("Photo library thumbnail grid")
    owner.library_grid.setVisible(False)
    owner.library_grid.itemSelectionChanged.connect(owner._library_selection_changed)
    owner.library_grid.itemDoubleClicked.connect(owner._open_library_item)
    layout.addWidget(owner.library_grid)
    owner.library_result = QLabel("Organise by time. Select days or photos to create a Topic.")
    owner.library_result.setObjectName("StatusSummary")
    owner.library_result.setWordWrap(True)
    layout.addWidget(owner.library_result)
    owner.library_technical_toggle = QCheckBox("Show advanced catalog details")
    owner.library_technical_toggle.setChecked(False)
    owner.library_technical_toggle.toggled.connect(owner._set_library_technical_visible)
    layout.addWidget(owner.library_technical_toggle)
    owner.library_thumbnail_button = QPushButton("Build missing thumbnails")
    owner.library_thumbnail_button.setToolTip("Create rebuildable previews beside the catalog; originals are read-only.")
    owner.library_thumbnail_button.clicked.connect(owner._start_thumbnail_generation)
    owner.library_thumbnail_button.setVisible(False)
    layout.addWidget(owner.library_thumbnail_button)
    owner.library_thumbnail_cancel_button = QPushButton("Cancel thumbnail build")
    owner.library_thumbnail_cancel_button.setEnabled(False)
    owner.library_thumbnail_cancel_button.setVisible(False)
    owner.library_thumbnail_cancel_button.clicked.connect(owner._cancel_thumbnail_generation)
    layout.addWidget(owner.library_thumbnail_cancel_button)
    owner.library_thumbnail_status = QLabel("Thumbnail cache status: not checked")
    owner.library_thumbnail_status.setVisible(False)
    layout.addWidget(owner.library_thumbnail_status)
    # Legacy controller fields remain available for existing bulk commands; the
    # compact Timeline UI intentionally keeps them out of the normal surface.
    owner.library_limit = QLineEdit("500")
    owner.library_limit.setVisible(False)
    owner.library_previous = QPushButton("Previous")
    owner.library_previous.setVisible(False)
    owner.library_next = QPushButton("Next")
    owner.library_next.setVisible(False)
    owner.library_assign_event = QComboBox()
    owner.library_assign_tag = QComboBox()
    owner.library_assign_place = QComboBox()
    owner.library_assign_person = QComboBox()
    for widget in (owner.library_assign_event, owner.library_assign_tag, owner.library_assign_place, owner.library_assign_person):
        widget.setVisible(False)
        layout.addWidget(widget)
    table = QTableWidget()
    table.setSortingEnabled(True)
    table.setVisible(False)
    tables["Library"] = table
