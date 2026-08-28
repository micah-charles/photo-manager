# PhotoVault Database Schema — Phases 1–14

The Phase 1 catalog lives in a user-selected SQLite database. Migrations are applied by `photovault.database.migrations`; application startup never creates arbitrary tables outside the migration registry.

## Tables

### `schema_migrations`

`version` is the primary key; `applied_at` stores a UTC timestamp.

### `volumes`

Persistent disk/folder record. `identity_kind`/`identity_value` hold the provider result; `current_mount_path` is mutable and never the canonical identity. macOS uses a `diskutil`-reported volume UUID when available, while non-macOS and provider failures use an explicit path fallback. `filesystem` and `capacity_bytes` are optional observations.

Columns: `id` primary key, `display_name`, `identity_kind`, unique `identity_value`, optional `filesystem` and `capacity_bytes`, `first_seen`, `last_seen`, mutable `current_mount_path`, and `status` (`CONNECTED`/`OFFLINE`).

### `assets`

Logical media record. Byte-identical locations are merged using SHA-256 while preserving all physical locations.

Columns: `id` primary key, `media_type`, `created_at`, `updated_at`.

### `asset_locations`

Physical file observation. `asset_id` references `assets`; `volume_id` references `volumes`; `(volume_id, relative_path)` is unique. Stores filename, size, modification nanoseconds, optional capture date, originating scan session and `missing_since`.

### `scan_sessions`

Resumability/audit record: volume, root path, timestamps, status (`RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`), files seen/catalogued and error count.

### `scan_errors`

Per-path scan failures linked to a session. Errors do not abort the complete scan unless the session-level operation itself fails.

## Indexes

- `asset_locations(volume_id)` for disk views
- `asset_locations(asset_id)` for logical asset locations
- `asset_locations(size_bytes)` for future hash candidate reduction
- `scan_sessions(volume_id)` for history

### `exact_hashes`

One authoritative SHA-256 row per logical asset. `asset_id` is the primary key; `sha256` is unique; `byte_count` and `hashed_at` support audit and cache inspection. When two locations hash identically, their `asset_locations` rows point to the same asset.

## Phase 11 visual similarity tables

`perceptual_hashes` stores one `dhash64` and/or `phash64` value per asset, with its computation timestamp. `duplicate_groups` records the algorithm and Hamming threshold used for one advisory run; `duplicate_group_members` stores group membership and observed distance. These tables do not replace `exact_hashes`, do not prove independent backup copies, and never authorize deletion.

## Phase 12 place tables

`place_clusters` stores a derived centroid, radius and optional reverse-geocoded label. `place_cluster_members` links catalogued assets to a cluster with their distance from the centroid. The default reverse geocoder is offline and produces coordinate-only places; a network or local-database geocoder must be injected explicitly.

## Phase 13 embedding table

`embeddings` stores a model-named JSON vector and the exact source SHA-256 used to compute it. Re-indexing an unchanged asset/model skips the engine; changed content is recomputed. Search is cosine similarity and remains independent of exact duplicate and backup safety decisions.

Volume connectivity is an observed state, not identity. `volume-refresh` and
the GUI Disks refresh compare each stored `current_mount_path` with the local
filesystem and update `volumes.status`; they do not delete locations or
metadata when a removable disk is absent.

All schema changes are applied through the migration registry; no ad-hoc tables are created at runtime.

## Phase 4 backup tables

`backup_sets` stores a named policy, required copy count and optional relative scope. `backup_set_members` assigns one volume as `PRIMARY` and one or more distinct volumes as `BACKUP`, with an optional per-volume relative root. A unique set/volume pair prevents accidentally assigning one physical volume twice.

The audit derives protection from active asset locations, exact SHA-256 identity and current volume status. It never treats a filename or size match as verified protection.

Phase 5 reconciliation is intentionally report-only and does not need new tables: it compares active `asset_locations` and `exact_hashes` for one primary/backup pair. CSV output is an exported report, not catalog state.

## Phase 6 operation tables

`operations` is the parent journal for copy/restore/quarantine/etc. Each `operation_items` row records source, destination, asset, expected hash, result and verification result. `verification_history` records expected versus actual destination SHA-256 and is written only after an attempted verification. A successful copy adds the verified destination as an `asset_location`; a failed or conflicting copy does not.

Folder safety audit uses existing catalog tables and the live selected folder. A cached offline copy is never counted as a currently verified copy when no connected copy is available; an unscanned live file makes the result unsafe.

Quarantine and undo use `operations`/`operation_items`; the manifest is a small JSON record stored beside quarantined files. The catalog source location is marked missing while quarantined and restored on successful undo. Quarantine is not treated as a backup-set volume.
