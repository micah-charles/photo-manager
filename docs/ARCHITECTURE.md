# PhotoVault Architecture

PhotoVault is a local-first desktop application. The CLI and optional PySide6 UI call the same Python application services; the UI does not implement its own backup logic.

```text
CLI / PySide6 UI
        |
backup services: audit, reconcile, copy, folder audit, quarantine
        |
catalog scanner + hashing + SQLite repositories
        |
platform providers (macOS volume UUID, Windows volume serial/GUID adapter)
```

Original files remain ordinary filesystem files. SQLite stores catalog metadata and operation history locally; thumbnail/cache and catalog backup policies will be added separately. The GUI is an integrity-first shell: Disks, Backup Sets, Operations, Copy Plans and Timeline have tables; Disks can be registered and Backup Sets can be created/membered without touching media; Scan, Redundancy Audit, Reconciliation, Folder Safety Audit, Visual Duplicates, Places, Quarantine and Undo Quarantine expose the existing services.

PySide6 is optional so the integrity core remains usable on headless systems and in automated tests. The packaging entry point is shared by macOS and Windows. File-backed GUI scans and confirmed copy/quarantine operations run in `QThread`s with separate SQLite connections; future long-running audit actions should use the same worker pattern.

Operational events use the standard-library `photovault` logger as compact JSON
records. Scan sessions and modifying operations retain authoritative SQLite
journals; logger events add start/end/error timing and identifiers for runtime
diagnostics without changing normal CLI output.
