# PhotoVault full product integration report

**Updated:** 2026-09-02  
**Primary repository:** `/Volumes/ExtremePro/project/codex/photo-manager-github`  
**Legacy reference:** `/Volumes/ExtremePro/project/photos`

## Executive summary

PhotoVault now has one safe Android production path: **PhotoVault Companion over
local Wi-Fi**. It is a read-only Android MediaStore server with HTTP Range
streaming, persistent installation identity, parallel verified import, and
SQLite-backed incremental history. It does not replace the existing
integrity-first catalog: SHA-256 verification, atomic publication, operation
history, backup sets, audits, reconciliation and quarantine remain the backup
truth.

The real Pixel 8 Pro baseline remains valid and must not be regressed:

| Metric | Verified result |
|---|---:|
| Camera items | 6,674 |
| Images / videos | 6,327 / 347 |
| Total payload | 64,498,996,810 bytes (64.50 GB) |
| Workers | 5 |
| Elapsed | 1,131.910 seconds (18m 52s) |
| Average throughput | 56,982,442 B/s (~57 MB/s) |
| Failures / partial files | 0 / 0 |
| SHA-256 verified | 6,674 |

The verified backup at `/Volumes/ExtremePro/PhotoVault-CameraRound1-Fresh` is
user data and is outside this repository. It must be treated as read-only.

## Product boundary

### Layer 1 — backup truth

- persistent device and volume identity
- source inventory, verified SHA-256 transfers and resumable partials
- incremental import history, profiles and snapshots
- backup sets, redundancy audit, reconciliation and reversible quarantine

### Layer 2 — photo experience

- timeline and folder-oriented catalog views
- thumbnails, places, visual duplicate candidates and favourites
- catalog-backed grid/preview, people/faces and optional semantic analysis

Layer 2 may read and annotate Layer 1. It never authorizes deletion, overwrite,
move or a change to verification truth.

## Current implementation status

| Area | Status | Current evidence / next work |
|---|---|---|
| Android Wi-Fi Companion | **COMPLETE — hardware baseline** | Pixel full Camera transfer passed with 5 workers at ~57 MB/s. Android MediaStore and HTTP Range remain the production transport. |
| Persistent Android identity | **COMPLETE — code; hardware install pending** | Android `SharedPreferences` installation UUID is exposed at `/api/device`; desktop derives source ID from it, not IP. Clearing app data/reinstall intentionally creates a new identity. |
| USB MTP | **BLOCKED / experimental** | Discovery, inventory and short PTP/MTP operations work; sustained reads fail in macOS IOUSBHost/libusb. It remains an explicitly labelled macOS fallback, never the default. |
| Cross-platform destination identity | **COMPLETE** | Wi-Fi copy no longer requires `/Volumes`; `register_volume()` selects macOS/Windows platform volume providers. |
| Verified transfer UI | **PARTIAL — live gate pending** | PySide6 Android page has Companion URL/token, folder totals, destination, all/image/video filter, advanced worker setting, cancel, resume, SHA-256 transfer, live telemetry and durable import-batch history. Needs unlocked live runtime validation. |
| General folder import | **COMPLETE — catalog-in-place entry point** | Import page previews mounted folder image/video counts and routes explicitly to Catalog in Place or reviewed Managed Copy; source files are never modified by the catalog path. |
| Event suggestions | **COMPLETE — deterministic review flow** | Date-density suggestions are catalog-only and support explicit Accept/Dismiss actions, with dismissal persistence. |
| Resume | **COMPLETE — core** | Range-capable source rehashes a retained partial then resumes; mismatch removes partial; interruption keeps it. |
| Incremental backup profiles | **COMPLETE — core/UI** | Migration 11 persists source/folder/filter/destination-volume profiles and completed/cancelled/failed snapshots; Android Devices includes profile picker, load/continue actions, and history. |
| Thumbnails | **COMPLETE — catalog + basic UI** | Existing thumbnail generation, cached previews, Library grid, selection and viewer routing are available; richer video preview remains future work. |
| Browse and preview | **COMPLETE — basic catalog UI** | Library provides catalog-backed filters, sorting, pagination, selection, cached preview and viewer routing; Events also has a contextual detail view with thumbnails and catalog-only membership removal. Event default places are surfaced as explicit inherited context when no asset place is assigned. |
| Favourites | **COMPLETE — catalog + UI** | Migration 12 stores non-destructive favourites and notes; Favourites page lists/edits them, Viewer has a visible toggle plus keyboard shortcut, and matched legacy gallery JSON can be imported safely. |
| Places | **PARTIAL — manual + clustering UI** | Offline GPS clustering and manual place creation/assignment/editing work; clustering radius is configured in Settings, while reverse-geocoding cache remains next. |
| Visual duplicates | **COMPLETE — catalog service / basic review UI** | dHash/pHash + BK-tree candidate grouping works; normal page is review-focused and analysis controls live under Settings. |
| Faces / people | **PARTIAL — manual + imported groups** | Person-group persistence, macOS Vision JSON import/browse, manual Person CRUD, and catalog-only assignment are available; import configuration is under Settings and Windows ONNX face backend remains next. |
| Semantic classification/search | **IN PROGRESS** | ONNX embedding index/search exists; labels, generated collections and UI search need integration. |
| Catalog backup / recovery | **COMPLETE — safe working-copy restore** | `catalog-backup` and `restore_catalog` use SQLite online backup API and verify new outputs; the UI restores to a new working catalog and never overwrites the active catalog or source backup. |
| macOS/Windows packaging | **PARTIAL** | macOS arm64 package and smoke test pass; Windows packaging/runtime/removable-drive validation remains outstanding. |

## Legacy migration matrix

| Feature | Legacy implementation | Current PhotoVault implementation | Migration disposition | Platform note |
|---|---|---|---|---|
| EXIF/GPS/capture dates | `organize_recent_photos.py`, Swift extractor | `catalog.metadata`, SQLite metadata tables | Reuse semantics; already catalog-backed | Portable Python metadata path |
| Thumbnails / HTML gallery | legacy generated thumbnails/gallery | `catalog.thumbnails`, static gallery export, timeline table | Build lazy grid/preview UI next | Video poster still needed |
| Vision faces / people | `extract_photo_features.swift` feature prints/clustering | `FaceEngine` protocol only | Add `MacVisionFaceEngine` adapter; persist people/assignments | macOS Vision; Windows ONNX later |
| Reverse geocoding | `resolve_location_names.swift`, JSON cache | offline GPS clusters | Import/reuse cache through optional adapter | Network reverse geocode must be opt-in |
| Favourites | browser JSON then copy/symlink export | `asset_favourites` catalog table + UI | Add legacy JSON importer and non-destructive export next | Never copy implicitly |
| dHash groups | `build_pic_similarity_gallery.py` | persisted dHash/pHash and BK-tree | Already migrated; enhance review UI | advisory only |
| CLIP/KMeans | `build_pic_clip_gallery.py` | ONNX embeddings/search | Map results to labels/collections; avoid fixed-K truth | model optional |
| Date/person/place virtual views | symlink output tree | catalog tables and timeline/places | Add saved collections + optional explicit export | no automatic moves |
| Backup / verification | not available | SHA-256, copy plans, audit, reconciliation | authoritative current implementation | cross-platform |

## Current desktop navigation

```text
Dashboard
Library
Import
Review
Events
Tags
Sources
Collections
People
Places
Categories
Disks
Android Devices      ← Companion Wi-Fi production entry point
Backup Sets
Scan
Redundancy Audit
Reconciliation
Folder Safety Audit
Copy Plans
Quarantine
Operations
Timeline
Favourites
Visual Duplicates
Places
```

Event Detail is a contextual page opened from Events; technical pages remain
reachable through Advanced Tools. Existing pages continue calling core
services rather than adding a second filesystem implementation inside the UI.

## Android Companion operational model

1. On Android, start sharing for 10 minutes, one hour, or until stopped (up to
   six hours). The foreground service/persistent notification permits screen
   off operation.
2. On desktop, enter the displayed URL and token in **Android Devices**.
3. Connect to verify device identity and inspect MediaStore folder totals.
4. Select a folder, media filter, profile name, existing destination and worker
   count. Default remains five workers based on hardware evidence.
5. PhotoVault inventories first, blocks conflicts, then transfers new items.
   Each completed item is SHA-256 verified before atomic rename and catalog
   registration.
6. Cancelling keeps a partial file. A future Wi-Fi attempt rehashes its prefix
   and uses HTTP Range to resume. Source files are never modified.

## Validation status

Automated test command:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Current result: **119 passed**. PySide6 is available in the project environment; the UI foundation subset is 24/24.
Core tests cover volume identity,
catalog migrations, verified copy safety, source import, Android Wi-Fi paging,
stable device identity, range resume, profiles/snapshots, favourites, metadata,
duplicates, places, backup audit and quarantine.

Manual verification still required:

- build/install the Companion APK that includes persistent identity;
- connect the actual Pixel via the PySide6 page and verify folders/totals;
- run a small UI backup to a disposable external-drive folder;
- cancel during a file and rerun to verify Range resume visibly;
- run a rendered PySide6 smoke test on macOS and a Windows smoke test;
- do not retest against or alter the protected Round 1 backup.

## Git implementation trail

Recent integration commits:

- `6a67789` Persist Android Companion installation identity
- `c1e4b89` Integrate Android Companion Wi-Fi discovery UI
- `9ab107a` Resume range-capable Android imports safely
- `4ae9177` Add cancellable Android Wi-Fi backup workflow
- `818d741` Show Android backup transfer telemetry
- `dffb45c` Persist Android backup profiles and snapshots
- `94b68b5` Add persistent catalog favourites
- `633a420` Import legacy gallery favourites into catalog
- `fb3b931` Add consistent catalog backup and integrity checks
- `bd9bed4` Add catalog-backed library browsing

## Next execution order

1. Install the newest Companion APK and complete the manual UI smoke test.
2. Add profile selector/history plus a dedicated Transfers page and CSV/JSON
   report export.
3. Build Library grid, thumbnail cache, preview/video poster and selection.
4. Add legacy-favourites JSON importer, saved collections and safe explicit
   export.
5. Migrate macOS Vision people adapter and add Windows ONNX counterpart.
6. Add reverse-geocode cache adapter, labels/semantic collections, then catalog
   online backup/recovery and macOS/Windows packaging.
