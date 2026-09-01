# PhotoVault UI Product Redesign Report

## 1. Current UI architecture

PhotoVault uses a shared Python application core, SQLite catalog, optional
PySide6 desktop UI, and platform adapters. `MainWindow` builds the remaining
pages and owns shared refresh/navigation state; the Operations/Activity page
has now been extracted into a dedicated page builder. Long-running scan, Android,
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
- Explore: People, Places, Categories, Visual Duplicates
- Backup: Android Devices, Backup Profiles, Backup Sets
- Storage: Disks, Backup Health, audits, and reconciliation
- Activity: Operations and Timeline
- Settings: Settings, Advanced Tools, Catalog Recovery and advanced catalog tools

The grouping is defined in `ui/spec.py`; the old services are not removed.

## 4. Files and classes added or changed

- `src/photovault/ui/theme.py`: centralized light-theme tokens and stylesheet
- `src/photovault/ui/spec.py`: grouped navigation contract
- `src/photovault/ui/main_window.py`: grouped sidebar, shared theme, global
  state, and navigation coordination
- `src/photovault/ui/pages/activity_page.py`, `collections_page.py`,
  `library_page.py`, `photo_viewer_page.py`, `android_backup_page.py`,
  `people_page.py`, `places_page.py`, `categories_page.py`,
  `duplicates_page.py`, `backup_profiles_page.py`, `backup_health_page.py`,
  `settings_page.py`, `advanced_tools_page.py`, `home_page.py`,
  `timeline_page.py`, and `favourites_page.py`: dedicated page
  builders for Activity, Collections, Library, Photo Viewer/Inspector,
  Android Backup, People, Places, Categories, Visual Duplicates, Backup
  Profiles, Backup Health, Settings, and Advanced Tools
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

The current implementation has working pages for Home/Dashboard, including a
live recent-photo thumbnail strip, Library
  thumbnail browsing, dedicated Photo Viewer/inspector, Collections, People, Places,
Favourites (with a Library smart-view handoff), Visual Duplicates, Android Devices, Backup Sets, Disks, Operations,
  Timeline, Categories, Backup Profiles, Backup Health, and the advanced storage tools. Collections and
  collections now also have a visible tile-grid entry point; tiles, album tiles,
  and table rows all route through the same Library opener. Categories can be
  opened by double-clicking a row and route to the normal Library grid. Users can create albums and add selected Library items without
  copying or moving originals.
  Settings and Advanced Tools now provide progressive-disclosure landing pages
  for the existing technical workflows.

## 7. Deviations from the mockup

The UI is still an incremental PySide6 migration rather than the final card
based redesign. The current catalog data is shown live; no mockup values or
fake people, drives, locations, or backup statistics are inserted. Categories
are currently model candidates from local ImageNet inference and are not yet
normalized into the final PhotoVault taxonomy. The Android page now has a
stateful status summary and dedicated connected-device card for connection,
inventory, copy, completion, failure, and cancellation while retaining
advanced connection controls.

## 8. Android workflow status

The proven read-only and Wi-Fi Companion paths remain in the shared source
architecture. The UI exposes Android connection and transfer controls and now
shows state-driven status, inventory totals, average speed, ETA, completion,
failure, a byte-based progress bar, safe cancellation/resume messaging, and a
live last-backup summary when the catalog has a completed run. New-item
delta calculation and a richer connected-device card remain P1 work.

## 9. Library and viewer status

Library supports real catalog queries, media filters, search/folder filters,
sorting, favourites, pagination, thumbnail grid selection, multi-select,
double-click/open, and single-item cached-thumbnail preview. The dedicated
Photo Viewer now provides previous/next navigation, Back to Library, real
metadata, location provenance, and verified-copy protection status. The grid
is the primary view; the raw asset table is hidden by default behind an
Advanced catalog-details toggle. Full-resolution/original loading remains
deliberately separate from the cached preview path.

## 10. Storage and Backup Health

The underlying storage safety tools remain available and use live catalog
data. Drives now show a user-facing connected/offline summary and live
storage-location cards while retaining the table for registered drive details.
Backup Health now aggregates the existing `audit_backup_set` reports
into a live protected/total/needs-attention summary and per-backup-set table;
the detailed audit pages remain available for technical review.

## 11. People, Places, Categories, and Duplicates

People supports importing existing macOS Vision derived memberships and now
shows real catalogued people groups as thumbnail cards; cards and table rows
open the corresponding photo-first Library view. Places
remain an advisory catalog view with offline-safe coordinate-cluster cards;
double-clicking a place card opens its catalogued photos. Visual duplicates now show real thumbnail
review rows and double-click into the normal Library view; they remain
advisory only. Local ONNX classification
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
environment from source control. A local PyInstaller macOS build was also
completed successfully with an arm64 `dist/PhotoVault.app`; its bundled
executable passed the `--help` smoke test. Windows packaging remains a CI or
real-Windows validation item.

## 14. Remaining known gaps

1. Replace the remaining flat page construction branches with page and
   reusable component modules; dedicated Activity, Collections, Library,
   Photo Viewer, Android Backup, People, Places, Categories, Visual
  Duplicates, Backup Profiles, Backup Health, Settings, Advanced Tools, Home,
  Timeline, and Favourites builders plus shared tile components are now in
  place.
2. Finish the photo-first Home and richer connected-device Android Backup
   workflow from the supplied mockup; the device card, status, progress, and
   profile flow are now available, while the final card composition remains.
3. Replace the remaining smart-collection table with richer visual cards;
   the first live tile-grid entry point is now present, and user-created albums
   have a live cover mosaic while preserving their catalog-only semantics.
4. Activity now has a readable recent-operation feed alongside the detailed
   audit table; Drives now have live location cards. Backup Health summary is now
   available from the grouped Storage navigation.
5. Normalize model labels into PhotoVault categories and move AI indexing into
   a cancellable UI worker.
6. Add cross-platform Windows volume/Android adapters and packaging checks.
7. Add final screenshot/regression validation for the redesigned shell and
   complete a real Windows packaged-app smoke test.

## 16. Cross-platform packaging note

The build instructions use a platform-neutral `<project-root>` placeholder;
they do not assume macOS `/Volumes` paths. The application uses `pathlib` and
the platform volume-provider boundary for drive behavior. macOS packaging has
passed locally; Windows packaging remains to be run on Windows.

## 15. Recommended next sprint

Build shared `PageHeader`, `PhotoGrid`, `PhotoTile`, `StatusBadge`,
`EmptyState`, and `PhotoInspector` components. Then redesign Home, Library,
Photo Detail, and Android Backup as one connected daily-use flow. Keep the
existing advanced pages behind the new navigation and verify all safety
boundaries with the current catalog and copy-operation tests.
