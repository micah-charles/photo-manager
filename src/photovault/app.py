from __future__ import annotations

import argparse
from pathlib import Path

from photovault.database.connection import connect
from photovault.ui.main_window import run_gui


def main() -> int:
    parser = argparse.ArgumentParser(prog="photovault-app")
    parser.add_argument("--catalog", type=Path, default=Path("~/.photovault/catalog.db"))
    connection = connect(parser.parse_args().catalog)
    try:
        return run_gui(connection)
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
