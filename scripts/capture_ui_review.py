"""Capture deterministic screenshots of the PhotoVault UI pages.

This is a read-only visual regression helper. It opens the supplied SQLite
catalog, refreshes each page, and writes only PNG screenshots to the output
directory; it never scans or modifies media.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PySide6.QtWidgets import QApplication

from photovault.database.connection import connect
from photovault.ui.main_window import MainWindow


PAGES = (
    "Dashboard", "Library", "Collections", "Android Devices", "Backup Health",
    "Advanced Tools", "People", "Places", "Categories", "Visual Duplicates",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    connection = connect(args.catalog)
    window = MainWindow(connection)
    window.resize(1280, 820)
    window.show()
    for page in PAGES:
        window._select_page(page)
        app.processEvents()
        name = page.lower().replace(" ", "-")
        if not window.grab().save(str(args.output / f"{name}.png")):
            raise RuntimeError(f"could not save screenshot for {page}")
    window.close()
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
