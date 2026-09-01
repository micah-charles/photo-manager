"""Backup-set policy page construction."""
from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QPushButton, QTableWidget


def build_backup_sets_page(owner: object, layout: object, tables: dict[str, QTableWidget]) -> None:
    """Build the advanced backup-set policy editor without exposing internals elsewhere."""
    create_form = QFormLayout()
    owner.backup_set_name = QLineEdit()
    owner.backup_set_copies = QLineEdit("2")
    owner.backup_set_scope = QLineEdit()
    create_form.addRow("Name", owner.backup_set_name)
    create_form.addRow("Required verified copies", owner.backup_set_copies)
    create_form.addRow("Scope (optional)", owner.backup_set_scope)
    layout.addLayout(create_form)

    create_button = QPushButton("Create backup set")
    create_button.clicked.connect(owner._create_backup_set)
    layout.addWidget(create_button)

    member_form = QFormLayout()
    owner.member_set_id = QLineEdit()
    owner.member_volume_id = QLineEdit()
    owner.member_role = QLineEdit("BACKUP")
    owner.member_relative_root = QLineEdit()
    member_form.addRow("Set ID", owner.member_set_id)
    member_form.addRow("Volume ID", owner.member_volume_id)
    member_form.addRow("Role (PRIMARY/BACKUP)", owner.member_role)
    member_form.addRow("Relative root", owner.member_relative_root)
    layout.addLayout(member_form)

    member_button = QPushButton("Add set member")
    member_button.clicked.connect(owner._add_backup_member)
    layout.addWidget(member_button)

    owner.backup_set_result = QLabel("Backup sets change catalog policy only; originals are never changed here.")
    owner.backup_set_result.setWordWrap(True)
    layout.addWidget(owner.backup_set_result)

    table = QTableWidget()
    table.setSortingEnabled(True)
    tables["Backup Sets"] = table
    layout.addWidget(table)
