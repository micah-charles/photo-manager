# PhotoVault UI Product Redesign Report

## 1. Current UI architecture

PhotoVault uses a shared Python application core, SQLite catalog, optional
PySide6 desktop UI, and platform adapters. `MainWindow` currently builds the
pages and owns shared refresh/navigation state. Long-running scan, Android,
copy, quarantine, and catalog-recovery work uses Qt worker threads. The
library reads the existing thumbnail cache rather than full-resolution media.

## 2. Main usability problems

The previous UI exposed nineteen technical pages as a flat sidebar. Photo
browsing was mixed with raw tables and advanced storage tools. Collections
required selecting a table row and pressing a button; photo-first workflows
and visual grouping were not obvious.

## 3. New information architecture

The sidebar now presents user-oriented groups while retaining stable page
names and page indexes for the existing services:

- Photos: Home, Library, Collections, Favourites
- Explore: People, Places, Visual Duplicates
- Backup: Android Devices, Backup Sets
- Storage: Disks, audits, and reconciliation
- Activity: Operations and Timeline
- Settings: Catalog Recovery and advanced catalog tools

The grouping is defined in `ui/spec.py`; the old services are not removed.

## 4. Files and classes added or changed

- `src/photovault/ui/theme.py`: centralized light-theme tokens and stylesheet
- `src/photovault/ui/spec.py`: grouped navigation contract
- `src/photovault/ui/main_window.py`: grouped sidebar, shared theme, and
  collection double-click interaction
- `src/photovault/catalog/collections.py`: catalog-derived browse views
- `src/photovault/catalog/classification.py`: optional local ONNX category
  indexing with resumable checkpoints
- `src/photovault/catalog/people_import.py`: macOS Vision derived-group import

## 5. Existing backend preserved

The redesign retains scanning, SHA-256 verification, copy plans, backup sets,
folder safety audit, redundancy audit, reconciliation, quarantine and undo,
catalog recovery, Android Companion flows, thumbnails, favourites, places,
visual duplicates, people import, and operation history. Originals remain
outside the catalog and are never changed by browsing or enrichment.

## 6. Mockup screens implemented

The current implementation has working pages for Home/Dashboard, Library
thumbnail browsing and inspector preview, Collections, People, Places,
Favourites, Visual Duplicates, Android Devices, Backup Sets, Disks, Operations,
Timeline, and the advanced storage tools. Collections can be opened by
double-clicking a row and now route to the normal Library grid.

## 7. Deviations from the mockup

The UI is still an incremental PySide6 migration rather than the final card
based redesign. The current catalog data is shown live; no mockup values or
fake people, drives, locations, or backup statistics are inserted. Categories
are currently model candidates from local ImageNet inference and are not yet
normalized into the final PhotoVault taxonomy.

## 8. Android workflow status

The proven read-only and Wi-Fi Companion paths remain in the shared source
architecture. The UI exposes Android connection and transfer controls, but the
state-driven connected-device card and polished backup progress/completion
flow remain P1 work.

## 9. Library and viewer status

Library supports real catalog queries, media filters, search/folder filters,
sorting, favourites, pagination, thumbnail grid selection, multi-select,
double-click/open, and single-item cached-thumbnail preview. The grid is now
the primary view; the raw asset table is hidden by default behind an Advanced
catalog-details toggle. The next redesign step is a fuller photo inspector
with provenance and backup-protection sections.

## 10. Storage and Backup Health

The underlying storage safety tools remain available and use live catalog
data. They are currently separate pages inside the grouped Storage/Settings
areas; a user-facing Backup Health summary card is still required.

## 11. People, Places, Categories, and Duplicates

People supports importing existing macOS Vision derived memberships. Places
and visual duplicates remain advisory catalog views. Local ONNX classification
stores hash-invalidated, rebuildable candidate labels in SQLite and exposes
them as category collections; it does not infer Google Photos locations or
modify originals.

## 12. Threading and performance

Existing file-backed operations use worker threads. Classification is a CLI
enrichment pass with checkpointed commits and an offset for safe resumption.
The desktop UI must use the same worker pattern before adding a one-click
background AI action. Thumbnail cache and paginated catalog queries prevent
full-resolution loading for the library.

## 13. Test results

The PySide6 UI foundation suite and full Python test suite pass in the
external `.venv`. The optional UI suite runs when PySide6 is present; headless
CI environments continue to skip those tests cleanly. The current working
tree intentionally excludes the external model, pip cache, and virtual
environment from source control.

## 14. Remaining known gaps

1. Replace the remaining flat page construction branches with page and
   reusable component modules.
2. Finish the photo-first Home, Library, viewer/inspector, and Android Backup
   workflows from the supplied mockup.
3. Add visual album cards and user-created collections while preserving smart
   collection semantics.
4. Add a user-facing Backup Health summary and readable Activity feed.
5. Normalize model labels into PhotoVault categories and move AI indexing into
   a cancellable UI worker.
6. Add cross-platform Windows volume/Android adapters and packaging checks.
7. Add final screenshot/regression validation for the redesigned shell.

## 15. Recommended next sprint

Build shared `PageHeader`, `PhotoGrid`, `PhotoTile`, `StatusBadge`,
`EmptyState`, and `PhotoInspector` components. Then redesign Home, Library,
Photo Detail, and Android Backup as one connected daily-use flow. Keep the
existing advanced pages behind the new navigation and verify all safety
boundaries with the current catalog and copy-operation tests.
