from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build PhotoVault with PyInstaller")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    probe = subprocess.run(
        [sys.executable, "-c", "import PyInstaller"],
        cwd=project,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe.returncode != 0:
        raise SystemExit("PyInstaller is not installed; run pip install -e '.[desktop,packaging]'")
    command = [sys.executable, "-m", "PyInstaller", "--name", "PhotoVault", "--windowed", "--noconfirm"]
    if args.clean:
        command.append("--clean")
    command.extend(["--paths", str(project / "src"), str(project / "src" / "photovault" / "app.py")])
    helper = project / "native" / "macos" / "android_mtp" / "photovault-android-mtp"
    if sys.platform == "darwin" and helper.exists():
        command.extend(["--add-binary", f"{helper}:native/macos/android_mtp"])
    config_dir = project / ".pyinstaller"
    config_dir.mkdir(exist_ok=True)
    environment = os.environ.copy()
    environment["PYINSTALLER_CONFIG_DIR"] = str(config_dir)
    return subprocess.call(command, cwd=project, env=environment)


if __name__ == "__main__":
    raise SystemExit(main())
