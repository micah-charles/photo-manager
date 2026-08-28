# PhotoVault

PhotoVault is a local-first desktop project for verifying photo/video backups across removable disks. It is being built separately from the legacy prototype at `/Volumes/ExtremePro/project/photos`.

Phase 1–3 provide a read-only SQLite catalog foundation, SHA-256 exact identity, stable-volume provider boundary and CLI. It does not copy, move, rename, quarantine, or delete media.

Phase 4–5 add read-only backup-set redundancy audits and Main/Backup reconciliation reports, including CSV export.

Phase 6 adds reviewed copy plans and execution with source revalidation, destination SHA-256 verification and operation history. Conflicting destinations are never overwritten.

Phase 7 adds the read-only `audit-folder` command for deciding whether an old folder is a safe removal candidate. It never performs the removal.

Phase 8 adds reversible quarantine and `undo-quarantine`. Files are hash-verified before and after the move, journalled, and never permanently deleted by this workflow. The GUI exposes dry-run Copy Plans, reversible Quarantine Plans and Undo Quarantine; execution requires an explicit confirmation and runs in a background worker.

Phase 9 adds the optional PySide6 GUI foundation. Install with `pip install -e '.[desktop]'`, then run `PYTHONPATH=src python3 -m photovault.ui --catalog /path/to/catalog.db` or the `gui` CLI command. The GUI can register disks, configure Backup Sets, run read-only audits/reconciliation, build reviewed copy/quarantine plans, and undo completed quarantine operations.

Phase 10 adds metadata/timeline/gallery commands, for example `photovault scan <volume-id> <root> --thumbnail-root ~/.photovault/thumbnails`, `photovault timeline`, and `photovault gallery ./gallery/index.html`.

Phase 11 adds persistent `dhash64`/`phash64` indexes and scalable BK-tree visual-similarity grouping. Install `pip install -e '.[photo-intelligence]'`, then run `perceptual-index` before `visual-duplicates`; these groups are advisory candidates only and never establish backup verification or permission to delete.

Phase 12 adds offline-safe GPS place clustering via `photovault places` and backend contracts for future macOS Vision/ONNX face detection. No geocoder network call or face analysis runs implicitly.

Phase 13 adds an engine-neutral persistent embedding store with SHA-256 invalidation and cosine search, plus an optional user-supplied ONNX/CLIP-compatible image encoder (`pip install -e '.[ml]'`). Use `embedding-index --model /path/model.onnx` and `embedding-search <model-name> --vector ...`; PhotoVault never downloads model weights. Phase 14 adds a Windows volume identity adapter; real Windows packaging/validation is still required before calling the port complete.

The desktop entry point is `photovault-app --catalog ~/.photovault/catalog.db`. From the GUI, register a disk, create a Backup Set and add its PRIMARY/BACKUP volumes; registration changes only the catalog, while scans run in a background worker. Build a macOS `.app` or Windows executable on the target OS with `python3 -m pip install -e '.[desktop,packaging]'` followed by `python3 scripts/build_app.py --clean`; see [packaging/README.md](packaging/README.md).

Design and safety details: [architecture](docs/ARCHITECTURE.md), [database schema](docs/DATABASE_SCHEMA.md), [backup model](docs/BACKUP_MODEL.md), [safety model](docs/SAFETY_MODEL.md), [Windows porting](docs/WINDOWS_PORTING.md), [ML backend](docs/ML_BACKEND.md), and [open-source landscape](docs/OPEN_SOURCE_LANDSCAPE.md).

## Quick start

```bash
cd /Volumes/ExtremePro/project/codex/photovault
python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m photovault.cli --help
```

Example:

```bash
PYTHONPATH=src python3 -m photovault.cli --catalog /tmp/photovault.db register /Volumes/ExtremePro
PYTHONPATH=src python3 -m photovault.cli --catalog /tmp/photovault.db scan <volume-id> /Volumes/ExtremePro
PYTHONPATH=src python3 -m photovault.cli --catalog /tmp/photovault.db volumes
# Refresh known disk status after disconnecting/reconnecting removable media.
PYTHONPATH=src python3 -m photovault.cli --catalog /tmp/photovault.db volume-refresh
```

The catalog is metadata only. Originals remain ordinary filesystem files.
