"""Central UI tokens and the light PhotoVault desktop theme."""
from __future__ import annotations

TOKENS = {
    "background": "#f7f8fb",
    "surface": "#ffffff",
    "border": "#dfe3eb",
    "text": "#172033",
    "muted": "#647084",
    "primary": "#1769e0",
    "primary_hover": "#0f56bf",
    "selection": "#e8f0ff",
}


def stylesheet() -> str:
    """Return one reusable stylesheet for all PhotoVault pages."""
    t = TOKENS
    return f"""
    QWidget {{ background: {t['background']}; color: {t['text']}; font-size: 13px; }}
    QMainWindow {{ background: {t['background']}; }}
    QListWidget, QTableWidget, QLineEdit, QPlainTextEdit, QComboBox {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; }}
    QListWidget#PhotoVaultNavigation {{ border: 0; border-right: 1px solid {t['border']}; border-radius: 0; padding: 10px 8px; }}
    QListWidget#PhotoVaultNavigation::item {{ padding: 8px 10px; border-radius: 7px; }}
    QListWidget#PhotoVaultNavigation::item:selected {{ background: {t['selection']}; color: {t['primary']}; font-weight: 600; }}
    QListWidget#PhotoVaultNavigation::item:hover {{ background: #eef3fb; }}
    QPushButton {{ background: {t['primary']}; color: white; border: 0; border-radius: 7px; padding: 8px 14px; min-height: 18px; }}
    QPushButton:hover {{ background: {t['primary_hover']}; }}
    QPushButton:disabled {{ background: #b9c3d2; color: #eef1f5; }}
    QLabel#PageTitle {{ font-size: 25px; font-weight: 700; padding: 8px 0; background: transparent; }}
    QLabel#SectionHeading {{ color: {t['muted']}; font-size: 11px; font-weight: 700; padding: 12px 10px 4px; }}
    QLabel#StatusBadge {{ color: {t['primary']}; font-size: 16px; font-weight: 700; background: {t['selection']}; border: 1px solid #c9dbff; border-radius: 8px; padding: 10px; }}
    QLabel#StatusSummary {{ color: {t['muted']}; background: transparent; padding: 2px 0 8px; }}
    QLabel#SettingsCard {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 12px; }}
    QListWidget#ReviewList {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 8px; }}
    QListWidget#RecentPhotoGrid {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 8px; min-height: 130px; }}
    QListWidget#CollectionGrid, QListWidget#AlbumGrid, QListWidget#PeopleGrid, QListWidget#PlacesGrid, QListWidget#DisksGrid {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 10px; min-height: 120px; }}
    QListWidget#CollectionGrid::item, QListWidget#AlbumGrid::item, QListWidget#PeopleGrid::item, QListWidget#PlacesGrid::item, QListWidget#DisksGrid::item {{ border: 1px solid transparent; border-radius: 8px; padding: 6px; margin: 4px; }}
    QListWidget#CollectionGrid::item:hover, QListWidget#AlbumGrid::item:hover, QListWidget#PeopleGrid::item:hover, QListWidget#PlacesGrid::item:hover, QListWidget#DisksGrid::item:hover {{ background: {t['selection']}; border-color: #c9dbff; }}
    QListWidget#CollectionGrid::item:selected, QListWidget#AlbumGrid::item:selected, QListWidget#PeopleGrid::item:selected, QListWidget#PlacesGrid::item:selected, QListWidget#DisksGrid::item:selected {{ background: {t['selection']}; border-color: {t['primary']}; }}
    QTableWidget {{ gridline-color: {t['border']}; selection-background-color: {t['selection']}; selection-color: {t['text']}; }}
    """
