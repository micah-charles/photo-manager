# Windows Porting Guide

PhotoVault keeps backup, catalog and reconciliation logic platform-neutral.
Platform-specific behavior is isolated behind volume providers and the shared
PySide6/PyInstaller entry point.

## Current adapter

`photovault.platform.windows.volume.WindowsVolumeProvider` calls
`GetVolumeInformationW` through `ctypes` and records a stable volume-serial
identity plus volume name/filesystem metadata. If the Windows API is
unavailable, it records an explicit `path_fallback` identity rather than
silently pretending the path is stable.

Core code consumes `VolumeIdentity`, not Windows APIs or drive letters.

## Packaging

Build on the target operating system:

```powershell
python -m pip install -e ".[desktop,packaging]"
python scripts/build_app.py --clean
```

PyInstaller produces a Windows executable under `dist/`. The bundle contains
the application only; it does not contain the catalog or photo originals.
Windows release validation still needs an actual Windows machine/runner,
including removable-drive mount behavior, Unicode paths, long paths,
interrupted copies, locked files and permission errors.

## CI gate

`.github/workflows/ci.yml` runs unit tests and compile checks on
`windows-latest`, and runs the packaging smoke build on both Windows and
macOS. Mocked Windows API tests validate the provider contract on other hosts;
they are not a substitute for the Windows runner.

The first Windows run exposed a test-harness portability issue rather than a
volume-provider failure: SQLite connections held open while
`TemporaryDirectory` cleaned up produced `WinError 32`. Test fixtures now close
connections before temporary directories are removed, and the affected local
regression group passes 56/56 tests.

## Remaining release checks

- Validate stable identity after drive-letter changes and remounts.
- Validate NTFS/exFAT paths, Unicode names and long-path policy.
- Validate copy verification and quarantine undo with Windows file handles.
- Inspect the packaged executable on a real Windows desktop.
- Add Windows code signing and installer/update policy before distribution.
- Select and validate a concrete ONNX embedding model with its required input
  shape and preprocessing; PhotoVault does not download model weights.
