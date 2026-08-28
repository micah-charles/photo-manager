from __future__ import annotations

import argparse
from pathlib import Path

from photovault.database.connection import connect
from .main_window import run_gui


def main() -> int:
    parser = argparse.ArgumentParser(prog="photovault-gui")
    parser.add_argument("--catalog", type=Path, default=Path("~/.photovault/catalog.db"))
    args = parser.parse_args()
    return run_gui(connect(args.catalog))


if __name__ == "__main__":
    raise SystemExit(main())
