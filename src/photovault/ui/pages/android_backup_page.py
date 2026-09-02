"""Android Backup page construction for the Companion workflow."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)


def build_android_backup_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    """Build connection, profile, and transfer controls without transfer logic."""
    owner.android_backup_status = QLabel("Not connected")
    owner.android_backup_status.setObjectName("StatusBadge")
    owner.android_backup_status.setWordWrap(True)
    layout.addWidget(owner.android_backup_status)
    owner.android_device_card = QLabel("No Android device connected\nConnect the read-only Companion over Wi-Fi to begin.")
    owner.android_device_card.setObjectName("SettingsCard")
    owner.android_device_card.setWordWrap(True)
    layout.addWidget(owner.android_device_card)
    owner.android_backup_summary = QLabel("Connect the read-only PhotoVault Companion over Wi-Fi, then choose a folder and destination.")
    owner.android_backup_summary.setObjectName("StatusSummary")
    owner.android_backup_summary.setWordWrap(True)
    layout.addWidget(owner.android_backup_summary)
    owner.android_backup_progress = QProgressBar()
    owner.android_backup_progress.setRange(0, 100)
    owner.android_backup_progress.setValue(0)
    owner.android_backup_progress.setTextVisible(True)
    owner.android_backup_progress.setFormat("Ready")
    layout.addWidget(owner.android_backup_progress)
    owner.android_backup_completion = QLabel("No backup completed in this session.")
    owner.android_backup_completion.setObjectName("SettingsCard")
    owner.android_backup_completion.setWordWrap(True)
    layout.addWidget(owner.android_backup_completion)
    completion_actions = QHBoxLayout()
    owner.android_view_photos_button = QPushButton("View Photos")
    owner.android_view_photos_button.setEnabled(False)
    owner.android_view_photos_button.clicked.connect(owner._view_android_backup_photos)
    completion_actions.addWidget(owner.android_view_photos_button)
    owner.android_view_details_button = QPushButton("View Backup Details")
    owner.android_view_details_button.setEnabled(False)
    owner.android_view_details_button.clicked.connect(owner._view_android_backup_details)
    completion_actions.addWidget(owner.android_view_details_button)
    owner.android_create_event_button = QPushButton("Create Event")
    owner.android_create_event_button.setEnabled(False)
    owner.android_create_event_button.clicked.connect(owner._create_event_from_android_batch)
    completion_actions.addWidget(owner.android_create_event_button)
    owner.android_review_button = QPushButton("Review Photos")
    owner.android_review_button.setEnabled(False)
    owner.android_review_button.clicked.connect(owner._review_android_batch)
    completion_actions.addWidget(owner.android_review_button)
    layout.addLayout(completion_actions)

    from photovault.cli.main import _default_android_helper

    owner.android_companion_url = QLineEdit("http://")
    owner.android_companion_token = QLineEdit()
    owner.android_companion_token.setEchoMode(QLineEdit.EchoMode.Password)
    owner.android_companion_token.setPlaceholderText("Token shown by PhotoVault Companion")
    companion_button = QPushButton("Connect Companion (Wi-Fi)")
    companion_button.clicked.connect(owner._discover_android_companion)
    owner.android_companion_discover_button = companion_button
    layout.addWidget(companion_button)
    owner.android_result = QLabel("Production path: connect the read-only Android Companion over Wi-Fi. The device identity remains stable when its IP address changes.")
    owner.android_result.setWordWrap(True)
    layout.addWidget(owner.android_result)

    advanced_toggle = QCheckBox("Show advanced connection settings")
    advanced_body = QWidget()
    advanced_body.setVisible(False)
    advanced_form = QFormLayout(advanced_body)
    advanced_form.addRow("Companion URL", owner.android_companion_url)
    advanced_form.addRow("Companion token", owner.android_companion_token)
    owner.android_helper = QLineEdit(str(_default_android_helper()))
    advanced_form.addRow("Native helper", owner.android_helper)
    usb_button = QPushButton("Discover USB MTP (experimental macOS fallback)")
    usb_button.clicked.connect(owner._discover_android)
    owner.android_discover_button = usb_button
    advanced_form.addRow("USB fallback", usb_button)
    advanced_toggle.toggled.connect(advanced_body.setVisible)
    layout.addWidget(advanced_toggle)
    layout.addWidget(advanced_body)

    transfer_group = QGroupBox("Backup setup")
    transfer_group.setEnabled(False)
    transfer_group.setVisible(False)
    owner.android_transfer_group = transfer_group
    transfer_layout = QVBoxLayout(transfer_group)
    transfer_form = QFormLayout()
    owner.android_transfer_folders = QPlainTextEdit("DCIM/Camera")
    owner.android_transfer_folders.setPlaceholderText("One MediaStore relative folder per line, e.g. DCIM/Camera")
    owner.android_transfer_profile_name = QLineEdit("Android Camera backup")
    owner.android_transfer_media_filter = QComboBox()
    owner.android_transfer_media_filter.addItem("Images and videos", "ALL")
    owner.android_transfer_media_filter.addItem("Images only", "IMAGE")
    owner.android_transfer_media_filter.addItem("Videos only", "VIDEO")
    owner.android_transfer_destination = QLineEdit()
    owner.android_transfer_workers = QLineEdit("5")
    transfer_layout.addWidget(QLabel("Phone folders"))
    owner.android_folder_selector = QListWidget()
    owner.android_folder_selector.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    owner.android_folder_selector.setMaximumHeight(170)
    owner.android_folder_selector.setToolTip("Select one or more shared phone folders for this backup.")
    owner.android_folder_selector.itemChanged.connect(owner._android_folder_selection_changed)
    transfer_layout.addWidget(owner.android_folder_selector)
    transfer_form.addRow("Backup folders", owner.android_transfer_folders)
    transfer_form.addRow("Profile name", owner.android_transfer_profile_name)
    transfer_form.addRow("Media", owner.android_transfer_media_filter)
    destination_row = QHBoxLayout()
    destination_row.addWidget(owner.android_transfer_destination, 1)
    owner.android_destination_browse = QPushButton("Browse…")
    owner.android_destination_browse.clicked.connect(owner._choose_android_destination)
    destination_row.addWidget(owner.android_destination_browse)
    transfer_form.addRow("Destination directory", destination_row)
    transfer_form.addRow("Concurrent workers", owner.android_transfer_workers)
    transfer_layout.addLayout(transfer_form)

    profile_actions = QHBoxLayout()
    owner.android_saved_profile = QComboBox()
    owner.android_saved_profile.setPlaceholderText("Saved backup profile")
    profile_actions.addWidget(owner.android_saved_profile, 1)
    refresh_profiles_button = QPushButton("Refresh profiles")
    refresh_profiles_button.clicked.connect(owner._refresh_android_backup_profiles)
    profile_actions.addWidget(refresh_profiles_button)
    load_profile_button = QPushButton("Load selected profile")
    load_profile_button.clicked.connect(owner._load_selected_android_backup_profile)
    profile_actions.addWidget(load_profile_button)
    continue_profile_button = QPushButton("Continue selected backup")
    continue_profile_button.clicked.connect(owner._continue_selected_android_backup_profile)
    profile_actions.addWidget(continue_profile_button)
    transfer_layout.addLayout(profile_actions)

    transfer_button = QPushButton("Start verified Wi-Fi backup")
    transfer_button.clicked.connect(owner._start_android_companion_transfer)
    owner.android_transfer_button = transfer_button
    transfer_layout.addWidget(transfer_button)
    cancel_transfer_button = QPushButton("Cancel transfer (partial files can resume)")
    cancel_transfer_button.setEnabled(False)
    cancel_transfer_button.clicked.connect(owner._cancel_android_companion_transfer)
    owner.android_transfer_cancel_button = cancel_transfer_button
    transfer_layout.addWidget(cancel_transfer_button)
    owner.android_transfer_result = QLabel("A transfer copies new items only, SHA-256 verifies each completed file, and never changes phone files.")
    owner.android_transfer_result.setWordWrap(True)
    transfer_layout.addWidget(owner.android_transfer_result)
    layout.addWidget(transfer_group)
    owner.android_profile_history = QTableWidget()
    owner.android_profile_history_label = QLabel("Saved profiles and recent runs")
    owner.android_profile_history_label.setVisible(False)
    layout.addWidget(owner.android_profile_history_label)
    layout.addWidget(owner.android_profile_history)

    table = QTableWidget()
    table.setVisible(False)
    tables["Android Devices"] = table
    layout.addWidget(table)
