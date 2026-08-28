# PhotoVault Implementation Plan

Date: 2026-08-21
Working name: PhotoVault

## Product priorities

1. Photo Backup Integrity Manager
2. Offline Multi-Drive Photo Catalog
3. Intelligent Photo Library

The application must answer whether important media has the required number of independently verified physical copies. Thumbnails, people, places, visual similarity and semantic search are secondary.

## Proposed architecture

Use a local desktop application with a Python core and PySide6/Qt UI. The core is callable from a CLI and has no UI dependency. SQLite is the initial catalog database, with versioned migrations. Files remain ordinary user-owned files in their existing folders; PhotoVault creates virtual views and metadata/cache, not a proprietary photo container.

```text
CLI / PySide6 UI
        |
Application services
  scanner | backup | audit | operations
        |
Catalog repository + migrations (SQLite)
        |
Platform adapters: volume, metadata, thumbnails, trash, reveal
```

## Proposed directory structure

```text
photovault/
  app/main.py
  cli.py
  catalog/{models.py,scanner.py,hashing.py,metadata.py,thumbnails.py}
  backup/{models.py,redundancy.py,reconciliation.py,copy_plan.py,verifier.py,folder_audit.py}
  duplicates/{exact.py,perceptual.py,similarity.py}
  database/{connection.py,migrations/,repositories/}
  operations/{journal.py,quarantine.py,undo.py}
  platform/{base.py,macos/,windows/}
  ui/{main_window.py,views/,widgets/}
  legacy/
  tests/
  docs/
```

Do not move or delete the existing scripts during Phase 0/1. They can be placed under `legacy/` only after import paths and generated outputs are understood.

## Data model

Core identity is content-based, not path-based.

- `Asset`: one logical exact-content item; authoritative identity is SHA-256 once hashed.
- `AssetLocation`: one physical file on one volume, with current relative path and observed file metadata.
- `Volume`: persistent removable-disk identity; current mount path is mutable metadata only.
- `BackupSet`: primary/backup roles, scope, minimum verified copies and policy.

Duplicate confidence is explicit: `EXACT_COPY`, `REENCODED_COPY`, `NEAR_DUPLICATE`, `SEMANTICALLY_SIMILAR`. Only exact cryptographic equality can establish a backup copy. Semantic similarity is never a deletion recommendation.

## Database schema

Initial normalized entities:

- `schema_migrations`
- `volumes`
- `backup_sets`
- `backup_set_members`
- `assets`
- `asset_locations`
- `media_metadata`
- `gps_metadata`
- `exact_hashes`
- `perceptual_hashes`
- `thumbnails`
- `scan_sessions`
- `scan_errors`
- `duplicate_groups`
- `duplicate_group_members`
- `operations`
- `operation_items`
- `verification_history`

Important indexes: `(volume_id, relative_path)`, `sha256`, `(file_size, quick_fingerprint)`, `asset_id`, `backup_set_id`, scan status and perceptual hash bucket. Foreign keys and unique constraints must prevent duplicate locations and duplicate hashes.

The detailed column-level design will be recorded in `docs/DATABASE_SCHEMA.md` when Phase 1 is implemented.

## File identity and hashing

1. Use volume ID + relative path only to locate a current observation.
2. Use size + mtime + optional quick fingerprint to avoid unnecessary rehashing.
3. Use SHA-256 as authoritative exact-content identity.
4. A renamed or moved identical file resolves to the same `Asset` and a new/updated `AssetLocation`.
5. Destination backup status becomes verified only after reading and hashing the destination and comparing SHA-256.

## Volume identity and offline behavior

`VolumeProvider` exposes a platform-neutral record. macOS should prefer filesystem UUID and reliable disk identifiers; Windows should use volume GUID/serial where available. Display name and mount path are not identity.

The catalog remains usable when a volume is offline. Cached metadata/thumbnails remain browsable, while protection status is marked `OFFLINE_UNKNOWN` when a required volume cannot be revalidated. Last verified state is retained.

## Backup/redundancy model

Minimum states:

- `VERIFIED_REDUNDANT`
- `MISSING_BACKUP`
- `BACKUP_ONLY`
- `CONFLICT`
- `UNPROTECTED`
- `MULTI_COPY`
- `OFFLINE_UNKNOWN`

Reconciliation compares logical assets and physical locations, not merely names. Same expected relative path with different SHA-256 is a conflict and is never overwritten automatically.

## Safety model

- Original photo/video files are never silently deleted.
- No automatic overwrite of conflicts.
- Copy, move, restore, quarantine and delete are journalled.
- Every copy plan supports dry-run and explicit review.
- Default removal is a reversible move into `.PhotoVaultQuarantine/` with manifest, original path, destination path, asset ID, SHA-256, operation ID, timestamp and reason.
- Permanent deletion is a separate explicit action.
- Interrupted scans and failed operations must leave the catalog consistent and resumable.

## Migration strategy

1. Keep legacy scripts and sample outputs unchanged.
2. Add catalog foundation and scan real folders read-only.
3. Import existing JSON/CSV only as optional historical metadata; never treat path-derived SHA-1 names as asset identity.
4. Add exact SHA-256 identity and volume identity.
5. Add backup sets, reconciliation and verified copy plans.
6. Add folder safety audit, quarantine and undo.
7. Add PySide6 GUI over the same services.
8. Integrate thumbnails/timeline/GPS/faces.
9. Add scalable perceptual similarity and later persistent embeddings.
10. Add Windows platform adapters and test on a real Windows machine.

## Phases and acceptance criteria

### Phase 0 — audit and plan (complete)

Deliver `EXISTING_PROJECT_AUDIT.md` and this plan. No original media changes.

### Phase 1 — catalog foundation (implemented in the new project)

Implemented in `src/photovault`: SQLite migration v1, volume registration, asset-location inventory, scan sessions, scan errors, incremental-safe file inventory, missing-file marking, and a CLI. Acceptance verified with temporary-directory tests and CLI smoke test. No copy/move/delete.

### Phase 2 — exact identity (implemented)

Implemented SHA-256 caching and exact duplicate grouping. A renamed or differently named byte-identical file becomes one `Asset` with multiple `AssetLocation` rows; unchanged size/mtime rows reuse the cached digest; replaced content becomes a new logical asset while old missing history is retained.

### Phase 3 — stable removable volume identity (implemented)

Implemented `VolumeProvider`, portable path fallback, macOS `diskutil info -plist` provider and the Windows volume-serial adapter. Registration upgrades a same-path Phase 1 record when a stronger identity becomes available. A provider with the same stable identity at a new mount path preserves the volume record and updates only `current_mount_path`; tests simulate this remount behavior. Real Windows filesystem and packaging validation remains the Phase 14 release gate.

### Phase 4 — backup sets and audit (implemented)

Implemented migration v3, backup-set/member services, CLI creation/member commands, and a read-only audit reporting protected, missing-backup, backup-only, conflict, unprotected and offline-unknown states plus protection percentage. Copy/reconciliation mutations remain intentionally deferred to Phase 5/6.

### Phase 5 — reconciliation (implemented)

Implemented a read-only pair reconciliation engine and `reconcile` CLI command. It matches same-path and renamed files by SHA-256, reports `VERIFIED`, `MAIN_ONLY`, `BACKUP_ONLY`, `CONFLICT` and `UNKNOWN_OFFLINE`, and can export CSV. No photo filesystem modification is performed.

### Phase 6 — copy plan and verification (implemented)

Implemented migration v4 operation journal, reviewable dry-run copy plans, source revalidation, safe no-overwrite behavior, destination SHA-256 verification, verification history and verified destination cataloging. Corrupt or conflicting destinations remain unverified and are never treated as backup copies.

### Phase 7 — folder safety audit (implemented)

Implemented `audit-folder` as a read-only catalog/filesystem cross-check. It reports verified elsewhere, unique, same-name conflicts, offline-only copies and unscanned files, and marks a folder `SAFE_CANDIDATE_FOR_REMOVAL` only when all current files have an active exact copy elsewhere and no uncertainty. It never removes the folder.

### Phase 8 — quarantine and undo (implemented)

Implemented reversible `.PhotoVaultQuarantine/<operation-id>/` moves, SHA-256 pre/post verification, manifest, operation journal entries, dry-run planning, conflict-safe behavior and `undo-quarantine`. Permanent deletion is not implemented.

### Phase 9 — GUI (foundation implemented)

Implemented optional PySide6 UI shell with navigation and views for Disks, Scan, Backup Sets, Redundancy Audit, Reconciliation, Folder Safety Audit and Operations. Reports call the same core services; the local macOS environment verifies the GUI with `QT_QPA_PLATFORM=offscreen`, while headless environments can continue using the core without the `desktop` extra.

### Phase 10 — photo library features (implemented)

Integrated optional Pillow EXIF/dimensions/GPS extraction, optional ffprobe video metadata, persistent metadata/GPS tables, asset-keyed thumbnail cache, timeline query and static local gallery export. Originals remain in place; gallery links reference originals and cache thumbnails.

### Phase 11 — visual duplicate grouping (implemented)

Added persistent dHash and pHash values, Hamming distance and BK-tree search to avoid an all-pairs scan. Visual groups distinguish re-encoded-copy candidates from near-duplicate candidates and remain advisory; exact SHA-256 and backup verification are separate safety decisions. `perceptual-index` and `visual-duplicates` do not modify media.

### Phase 12 — people / places foundation (implemented, backend-ready)

Added persisted GPS place clusters using haversine distance, an offline-safe reverse-geocoder protocol, the `places` CLI command, and a platform-neutral `FaceEngine`/`FaceObservation` contract with an explicit unavailable backend. macOS Vision and ONNX face implementations remain optional follow-up adapters; face recognition does not block integrity features.

### Phase 13 — semantic search foundation (implemented, engine-neutral)

Added persistent model-named embeddings, source-SHA-256 cache invalidation, cosine search and an `EmbeddingEngine` protocol. The optional `OnnxEmbeddingEngine` accepts a user-supplied rank-4 RGB ONNX/CLIP-compatible image model and validates its input shape before indexing; PhotoVault never downloads model weights or runs ML implicitly. CLI entry points are `embedding-index` and `embedding-search`. Concrete model selection and face-recognition adapters remain user-configured follow-up work.

### Phase 14 — Windows port foundation

Added a Windows volume provider using Windows volume serial/name APIs with path fallback. Packaging and validation on an actual Windows machine remain release work.

Added a macOS/Windows CI matrix for unit tests and PyInstaller packaging smoke builds. The current local machine cannot prove the Windows runner result; CI is the authoritative cross-platform gate.

Added mocked Windows API tests covering stable volume-serial identity and path fallback. These validate adapter behavior on macOS but are not a substitute for the Windows CI runner.

The macOS packaging path is now locally proven: the project-local venv built `dist/PhotoVault.app` with PyInstaller, and the packaged arm64 executable passed `--help` plus code-signature/bundle inspection. The bundle is ad hoc signed and still needs production Developer ID signing/notarization.

The GUI now registers disk roots and creates/adds Backup Set members directly, and its file-backed scan runs in a background Qt worker with a separate catalog connection. These controls only change catalog state; they do not copy, move or delete media.

Confirmed Copy Plan and Quarantine Plan execution now also runs in a background worker with a separate SQLite connection. Copy execution retains source SHA-256 revalidation and no-overwrite conflict behavior; quarantine execution retains manifest, verification and undo semantics.

Operations now exposes Undo Quarantine in the GUI; it confirms the operation, re-hashes the quarantined source, refuses conflicting originals and restores catalog state only after verification.

## Testing strategy

Use temporary directories and synthetic files only. Required tests include exact duplicate, same-name/different-content conflict, missing backup, backup-only, safe/unsafe folder audit, corrupt destination verification, offline volume, rename/move identity preservation, interrupted scan recovery, and quarantine undo. Tests must not touch the user's real disks.

## Known risks and assumptions

- Some removable filesystems may not expose a stable serial/UUID consistently; provider must record evidence and degrade to a documented fallback.
- SHA-256 of very large libraries is I/O-heavy; caching and resumable jobs are required.
- A “backup” is only independently useful if it is on a distinct physical volume; the model should show physical volume count separately from file-copy count.
- Existing face extraction may be slow and macOS-only; it remains optional.
- Video metadata and thumbnails require cross-platform tooling and should be added early to cataloging even if advanced analysis is deferred.
- Catalog backup/export is required because the catalog is valuable metadata but must never be necessary to recover originals.
- Sidecar `.photovault/volume.json` is optional future metadata; its identity, privacy and staleness trade-offs must be documented before implementation.

## V1 definition of done

V1 is complete only when removable disks, offline cataloging, stable asset identity, SHA-256 verification, backup sets, reconciliation, copy plans, dry-run, verified copying, operation journal, folder safety audit, quarantine/undo, basic PySide6 GUI and automated integrity tests all work without modifying originals by default.
