"""Small reusable Qt components shared by the photo-first pages.

The components deliberately contain presentation only.  They do not query the
catalog or perform file operations, so pages remain responsible for data and
safety decisions.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem


class PhotoGrid(QListWidget):
    """Shared photo-first grid with safe thumbnail-sized interaction defaults."""

    def __init__(
        self,
        *,
        object_name: str = "PhotoGrid",
        icon_size: tuple[int, int] = (160, 120),
        grid_size: tuple[int, int] = (190, 170),
        multi_select: bool = True,
    ) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.setAccessibleName("Photo thumbnail grid")
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setIconSize(QSize(*icon_size))
        self.setGridSize(QSize(*grid_size))
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
            if multi_select else QAbstractItemView.SelectionMode.SingleSelection
        )

    def show_empty_state(self, message: str) -> None:
        """Show a non-actionable empty state without leaving stale tiles."""
        self.clear()
        item = QListWidgetItem(message)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.addItem(item)


def configure_tile_grid(
    widget: QListWidget,
    object_name: str,
    *,
    icon_size: tuple[int, int] = (150, 100),
    grid_size: tuple[int, int] = (190, 140),
) -> None:
    """Apply the common photo-first grid behavior used by browse pages."""
    widget.setObjectName(object_name)
    widget.setViewMode(QListWidget.ViewMode.IconMode)
    widget.setResizeMode(QListWidget.ResizeMode.Adjust)
    widget.setIconSize(QSize(*icon_size))
    widget.setGridSize(QSize(*grid_size))


def clear_tile_grid(widget: QListWidget, empty_text: str) -> None:
    """Clear a grid and leave a visible, non-actionable empty state."""
    widget.clear()
    widget.addItem(empty_text)


def add_tile(
    widget: QListWidget,
    title: str,
    subtitle: str,
    *,
    user_data: Any = None,
    icon_path: str | Path | None = None,
    tooltip: str = "",
) -> QListWidgetItem:
    """Add one consistent browse tile and return it for optional customization."""
    item = QListWidgetItem(f"{title}\n{subtitle}")
    if icon_path and Path(icon_path).is_file():
        item.setIcon(QIcon(str(icon_path)))
    if tooltip:
        item.setToolTip(tooltip)
    if user_data is not None:
        item.setData(Qt.ItemDataRole.UserRole, user_data)
    widget.addItem(item)
    return item
