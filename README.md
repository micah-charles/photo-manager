# Photo Manager

Photo Manager is a local-first desktop project for verifying photo/video backups across removable disks. The internal Python package remains `photovault` for compatibility.

Phase 1–3 provide a read-only SQLite catalog foundation, SHA-256 exact identity, stable-volume provider boundary and CLI. It does not copy, move, rename, quarantine, or delete media.

Phase 4–5 add read-only backup-set redundancy audits and Main/Backup reconciliation reports, including CSV export.

Phase 6 adds reviewed copy plans and execution with source revalidation, destination SHA-256 verification and operation history. Conflicting destinations are never overwritten.

Phase 7 adds the read-only `audit-folder` command for deciding whether an old folder is a safe removal candidate. It never performs the removal.

Phase 8 adds reversible quarantine and `undo-quarantine`. Files are hash-verified before and after the move, journalled, and never permanently deleted by this workflow. The GUI exposes dry-run Copy Plans, reversible Quarantine Plans and Undo Quarantine; execution requires an explicit confirmation and runs in a background worker.

Phase 9 adds the optional PySide6 GUI foundation. Install with `pip install -e '.[desktop]'` (including Pillow for rebuildable thumbnail previews), then run `PYTHONPATH=src python3 -m photovault.ui --catalog /path/to/catalog.db` or the `gui` CLI command. The GUI can register disks, configure Backup Sets, run read-only audits/reconciliation, build reviewed copy/quarantine plans, and undo completed quarantine operations.

Phase 10 adds metadata/timeline/gallery commands, for example `photovault scan <volume-id> <root> --thumbnail-root ~/.photovault/thumbnails`, `photovault timeline`, and `photovault gallery ./gallery/index.html`.

Phase 11 adds persistent `dhash64`/`phash64` indexes and scalable BK-tree visual-similarity grouping. Install `pip install -e '.[photo-intelligence]'`, then run `perceptual-index` before `visual-duplicates`; these groups are advisory candidates only and never establish backup verification or permission to delete.

## JPEG/RAW consolidation

`consolidate-pairs` is a safe, repeatable photo-management operation for cameras
that write JPEG and RAW files to separate folders. It pairs files by filename
stem, reports unmatched files, includes videos, chooses the embedded capture
date (falling back to filesystem modified date), and plans date-folder moves without changing
file bytes, names, or metadata. Run it once without `--move` to review; use
`--move` only after reviewing the conflict/unmatched counts:

```sh
PYTHONPATH=src python -m photovault --catalog /path/to/catalog.db \
  consolidate-pairs /path/to/jpeg-folder /path/to/raw-folder \
  --destination /path/to/organized
```

The operation refuses destination conflicts and is safe to repeat after an
interruption. Files already in the correct date folder are skipped.

Phase 12 adds offline-safe GPS place clustering via `photovault places` and backend contracts for future macOS Vision/ONNX face detection. No geocoder network call or face analysis runs implicitly.

Phase 13 adds an engine-neutral persistent embedding store with SHA-256 invalidation and cosine search, plus an optional user-supplied ONNX/CLIP-compatible image encoder (`pip install -e '.[ml]'`). Use `embedding-index --model /path/model.onnx` and `embedding-search <model-name> --vector ...`; PhotoVault never downloads model weights. Phase 14 adds a Windows volume identity adapter; real Windows packaging/validation is still required before calling the port complete.

The desktop entry point is `photovault-app --catalog ~/.photovault/catalog.db`. From the GUI, register a disk, create a Backup Set and add its PRIMARY/BACKUP volumes; registration changes only the catalog, while scans run in a background worker. Build a macOS `.app` or Windows executable on the target OS with `python3 -m pip install -e '.[desktop,packaging]'` followed by `python3 scripts/build_app.py --clean`; see [packaging/README.md](packaging/README.md).

Design and safety details: [architecture](docs/ARCHITECTURE.md), [database schema](docs/DATABASE_SCHEMA.md), [backup model](docs/BACKUP_MODEL.md), [safety model](docs/SAFETY_MODEL.md), [Windows porting](docs/WINDOWS_PORTING.md), [ML backend](docs/ML_BACKEND.md), and [open-source landscape](docs/OPEN_SOURCE_LANDSCAPE.md).

## Quick start

```bash
cd <project-root>
python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m photovault.cli --help
```

Example:

```bash
PYTHONPATH=src python3 -m photovault.cli --catalog /tmp/photovault.db register /path/to/source-volume
PYTHONPATH=src python3 -m photovault.cli --catalog /tmp/photovault.db scan <volume-id> /path/to/source-volume
PYTHONPATH=src python3 -m photovault.cli --catalog /tmp/photovault.db volumes
# Refresh known disk status after disconnecting/reconnecting removable media.
PYTHONPATH=src python3 -m photovault.cli --catalog /tmp/photovault.db volume-refresh
```

The catalog is metadata only. Originals remain ordinary filesystem files.

## Experimental Smart Collage POC

Phase 1 is an isolated, read-only layout experiment. It does not change the
catalog or source photographs. Given a folder of images, it writes 30
structured layout candidates (10 each from native, CEWE Fan genetic and BSP
providers), individual JPEG previews, a labelled contact sheet and
`candidates.json`:

```bash
PYTHONPATH=src python -m photovault.cli collage-poc /path/to/photos /tmp/collage-poc --limit 15 --seed 42
```

See [the audit and Phase 1 boundary](docs/smart-collage-poc-audit.md). Face
protection, ranking and review UI are intentionally later phases pending
visual review of these outputs.

In the web Library, click a Topic to open its photos, click `Edit` to change
its name or date range, and use `Create Topic` for a new one. Photo cards can
be dragged onto a Topic card; alternatively select several cards and choose a
Topic from the selection bar. These actions update only event membership and
catalog metadata.

## Local web Library

The Timeline-first Library is also available as a loopback-only web UI. It
reads the selected SQLite catalog, serves cached thumbnails, and never exposes
original media or binds to the LAN by default:

```bash
PYTHONPATH=src python3 -m photovault.cli \
  --catalog /path/to/catalog.db \
  web
```

Open `http://127.0.0.1:8765`. The first web slice includes month navigation,
day-grouped thumbnails, filter drawer, selection state, and the metadata
inspector. The same Python catalog and safety rules remain the source of truth.

Optional macOS Android support is integrated as a PhotoSource provider, not a
separate application. The native IOUSBHost helper supports device, storage,
lazy MTP folder metadata, bounded media streaming, and verified import with
incremental source/destination records. Real-device and packaged-distribution
validation remain environment-dependent; see [Android integration](docs/ANDROID_INTEGRATION_FINAL_REPORT.md).

## Secure Android Wi-Fi pairing

Install the generated Companion APK on the Pixel, start local sharing, and
tap **Pair new computer**. In the Photo Manager web UI open **Android Backup**;
the discovered phone appears under **Your Android devices**. Click **Pair**,
compare the six-digit SAS shown on both devices, confirm on the phone, then
confirm in Photo Manager. The UI fills the secure session credential into the
backup form; no phone token is needed for the new APK.

Create the backup plan and start it as usual. The existing range reads,
SHA-256 verification, atomic writes, worker pool, batch fsync, resume and
already-copied skipping remain unchanged. The secure session is short-lived;
long-running jobs automatically perform a pinned Noise reconnect and retry
after expiry. **Forget** removes the desktop trust record; the Companion also
provides **Forget paired computers** to clear its phone-side trust. Pairing
must then be performed again. Older APKs remain available through the explicitly labelled
legacy URL/token fields.

For an AI/MCP caller, pass `session_token` and `android_fingerprint` returned
by the secure pairing flow to `create_backup_job`, then call
`start_backup_job` and poll `backup_status`.
