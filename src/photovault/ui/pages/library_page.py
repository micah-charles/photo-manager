"""Photo-first Library page construction."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)

from ..components import PhotoGrid


def build_library_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    """Build the visual library while leaving query and safety policy to owner."""
    header = QHBoxLayout()
    owner.library_search = QLineEdit()
    owner.library_search.setPlaceholderText("Search photos by filename or path…")
    header.addWidget(owner.library_search, 1)
    refresh_button = QPushButton("Refresh")
    refresh_button.clicked.connect(owner._refresh_library)
    header.addWidget(refresh_button)
    layout.addLayout(header)

    filters = QHBoxLayout()
    owner.library_folder = QLineEdit()
    owner.library_folder.setPlaceholderText("Folder prefix")
    filters.addWidget(owner.library_folder, 2)
    owner.library_media_type = QComboBox()
    owner.library_media_type.addItems(["ALL", "IMAGE", "VIDEO"])
    filters.addWidget(owner.library_media_type)
    owner.library_sort = QComboBox()
    owner.library_sort.addItem("Capture date — newest", "captured_desc")
    owner.library_sort.addItem("Capture date — oldest", "captured_asc")
    owner.library_sort.addItem("Filename", "name_asc")
    owner.library_sort.addItem("Largest first", "size_desc")
    filters.addWidget(owner.library_sort, 2)
    owner.library_favourites_only = QCheckBox("Favourites only")
    filters.addWidget(owner.library_favourites_only)
    owner.library_limit = QLineEdit("200")
    owner.library_limit.setMaximumWidth(70)
    owner.library_limit.setToolTip("Maximum items loaded into the current page")
    filters.addWidget(owner.library_limit)
    layout.addLayout(filters)

    organisation = QHBoxLayout()
    organisation_label = QLabel("Organise by")
    organisation_label.setToolTip("These filters use catalog metadata and do not rescan or modify originals.")
    organisation.addWidget(organisation_label)
    owner.library_source_filter = QComboBox()
    owner.library_source_filter.setMinimumWidth(150)
    owner.library_source_filter.setToolTip("Source provenance")
    organisation.addWidget(owner.library_source_filter)
    owner.library_event_filter = QComboBox()
    owner.library_event_filter.setMinimumWidth(150)
    owner.library_event_filter.setToolTip("Event")
    organisation.addWidget(owner.library_event_filter)
    owner.library_tag_filter = QComboBox()
    owner.library_tag_filter.setMinimumWidth(130)
    owner.library_tag_filter.setToolTip("Tag")
    organisation.addWidget(owner.library_tag_filter)
    owner.library_place_filter = QComboBox()
    owner.library_place_filter.setMinimumWidth(130)
    owner.library_place_filter.setToolTip("Manual or embedded place")
    organisation.addWidget(owner.library_place_filter)
    owner.library_review_filter = QComboBox()
    owner.library_review_filter.addItem("Any review status", "")
    owner.library_review_filter.addItem("Unreviewed", "UNREVIEWED")
    owner.library_review_filter.addItem("Picked", "PICKED")
    owner.library_review_filter.addItem("Rejected", "REJECTED")
    owner.library_review_filter.addItem("Hidden", "HIDDEN")
    organisation.addWidget(owner.library_review_filter)
    owner.library_rating_filter = QComboBox()
    owner.library_rating_filter.addItem("Any rating", None)
    for rating in range(1, 6):
        owner.library_rating_filter.addItem(f"{rating}+ stars", rating)
    organisation.addWidget(owner.library_rating_filter)
    owner.library_include_rejected = QCheckBox("Include rejected/hidden")
    owner.library_include_rejected.setToolTip("Show items normally hidden from Library")
    organisation.addWidget(owner.library_include_rejected)
    clear_filters_button = QPushButton("Clear")
    clear_filters_button.setToolTip("Clear organisation filters")
    clear_filters_button.clicked.connect(owner._clear_library_organisation_filters)
    organisation.addWidget(clear_filters_button)
    layout.addLayout(organisation)
    for combo in (
        owner.library_source_filter, owner.library_event_filter, owner.library_tag_filter,
        owner.library_place_filter, owner.library_review_filter, owner.library_rating_filter,
    ):
        combo.currentIndexChanged.connect(owner._refresh_library)
    owner.library_include_rejected.toggled.connect(owner._refresh_library)

    owner.library_collection_result = QLabel("All catalogued media")
    owner.library_collection_result.setObjectName("StatusSummary")
    owner.library_collection_result.setWordWrap(True)
    layout.addWidget(owner.library_collection_result)

    actions = QHBoxLayout()
    clear_collection_button = QPushButton("Clear collection")
    clear_collection_button.clicked.connect(owner._clear_library_collection)
    actions.addWidget(clear_collection_button)
    favourite_button = QPushButton("Toggle favourite")
    favourite_button.clicked.connect(owner._toggle_selected_library_favourites)
    actions.addWidget(favourite_button)
    actions.addWidget(QLabel("Review:"))
    owner.library_review_action = QComboBox()
    owner.library_review_action.addItem("Pick", "PICKED")
    owner.library_review_action.addItem("Reject", "REJECTED")
    owner.library_review_action.addItem("Hide", "HIDDEN")
    owner.library_review_action.addItem("Mark unreviewed", "UNREVIEWED")
    actions.addWidget(owner.library_review_action)
    review_button = QPushButton("Apply")
    review_button.clicked.connect(owner._apply_selected_review)
    actions.addWidget(review_button)
    owner.library_rating_action = QComboBox()
    owner.library_rating_action.addItem("No rating change", None)
    for rating in range(1, 6):
        owner.library_rating_action.addItem(f"Rate {rating}★", rating)
    actions.addWidget(owner.library_rating_action)
    rate_button = QPushButton("Rate")
    rate_button.clicked.connect(owner._apply_selected_rating)
    actions.addWidget(rate_button)
    actions.addStretch(1)
    thumbnail_button = QPushButton("Build missing thumbnails")
    thumbnail_button.setToolTip("Create rebuildable previews beside the catalog; originals are read-only.")
    thumbnail_button.clicked.connect(owner._start_thumbnail_generation)
    owner.library_thumbnail_button = thumbnail_button
    actions.addWidget(thumbnail_button)
    layout.addLayout(actions)

    collection_actions = QHBoxLayout()
    owner.library_collection_target = QComboBox()
    owner.library_collection_target.addItem("Add selected photos to album…", None)
    collection_actions.addWidget(owner.library_collection_target, 1)
    add_collection_button = QPushButton("Add selected")
    add_collection_button.clicked.connect(owner._add_selected_to_collection)
    collection_actions.addWidget(add_collection_button)
    layout.addLayout(collection_actions)

    owner.library_result = QLabel("Catalog-backed results remain visible when an original volume is offline.")
    owner.library_result.setObjectName("StatusSummary")
    owner.library_result.setWordWrap(True)
    layout.addWidget(owner.library_result)
    owner.library_selection_count = QLabel("0 selected")
    layout.addWidget(owner.library_selection_count)
    owner.library_technical_toggle = QCheckBox("Show advanced catalog details")
    owner.library_technical_toggle.setChecked(False)
    owner.library_technical_toggle.toggled.connect(owner._set_library_technical_visible)
    layout.addWidget(owner.library_technical_toggle)

    browser_layout = QHBoxLayout()
    owner.library_grid = PhotoGrid(object_name="PhotoGrid")
    owner.library_grid.itemSelectionChanged.connect(owner._library_selection_changed)
    owner.library_grid.itemDoubleClicked.connect(owner._open_library_item)
    owner.library_grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    owner.library_grid.customContextMenuRequested.connect(owner._library_context_menu)
    owner.library_grid.show_empty_state("No photos indexed yet")
    browser_layout.addWidget(owner.library_grid, 3)

    preview_layout = QVBoxLayout()
    owner.library_preview = QLabel("Select a catalogued item to preview its cached thumbnail.")
    owner.library_preview.setWordWrap(True)
    owner.library_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    owner.library_preview.setMinimumSize(260, 220)
    preview_layout.addWidget(owner.library_preview, 1)
    owner.library_preview_details = QLabel("Original availability appears here.")
    owner.library_preview_details.setWordWrap(True)
    preview_layout.addWidget(owner.library_preview_details)
    browser_layout.addLayout(preview_layout, 2)
    layout.addLayout(browser_layout, 1)

    cancel_thumbnail_button = QPushButton("Cancel thumbnail build")
    cancel_thumbnail_button.setEnabled(False)
    cancel_thumbnail_button.clicked.connect(owner._cancel_thumbnail_generation)
    owner.library_thumbnail_cancel_button = cancel_thumbnail_button
    layout.addWidget(cancel_thumbnail_button)
    owner.library_thumbnail_status = QLabel("Thumbnail cache status: not checked")
    owner.library_thumbnail_status.setWordWrap(True)
    layout.addWidget(owner.library_thumbnail_status)

    table = QTableWidget()
    table.setSortingEnabled(True)
    table.setVisible(False)
    tables["Library"] = table
    layout.addWidget(table)
