# PhotoVault Phase 0 — Existing Project Audit

Date: 2026-08-21
Scope: `/Volumes/ExtremePro/project/photos`

## Executive summary

This folder is a macOS-oriented photo-management prototype, not yet a desktop application. It already has useful implementations for EXIF/GPS extraction, Apple Vision/CoreML face clustering, thumbnail/gallery generation, favourites export, perceptual similarity grouping, and an experimental CLIP/KMeans grouping flow.

The existing code does not yet provide the integrity product required by PhotoVault: a persistent cross-disk catalog, stable volume identity, SHA-256 content identity, verified copy operations, backup-set reconciliation, folder safety audits, operation journaling, quarantine/undo, or a GUI.

The safest migration approach is to preserve the existing scripts as legacy/reference implementations and build a new catalog/integrity core beside them. Existing photo files must remain untouched.

## Inventory

### Source scripts

| File | Current responsibility | Disposition |
|---|---|---|
| `organize_recent_photos.py` | Main macOS organizer; invokes Swift feature extraction, groups by date/person/GPS, reverse-geocodes locations, writes symlink views, thumbnails, JSON/CSV and HTML gallery | REFACTOR behind adapters; preserve output logic initially |
| `extract_photo_features.swift` | Recursive image enumeration, EXIF/GPS extraction, Vision face detection and feature-print clustering | KEEP temporarily as `MacVisionFaceEngine` adapter; not a V1 blocker |
| `resolve_location_names.swift` | Apple CoreLocation reverse geocoding | KEEP as macOS adapter; make optional |
| `export_favorite_photos.py` | Copies or symlinks browser-selected favourites by date and writes CSV/README | KEEP as legacy export; later call catalog service |
| `group_test_pic.py` | Early date + dHash similarity grouping; symlink/copy output | EXPERIMENTAL/legacy; replace with catalog-backed duplicate service |
| `build_pic_similarity_gallery.py` | dHash/Hamming visual similarity clustering and HTML gallery | REUSE algorithm concept; refactor to persistent perceptual hashes |
| `build_pic_clip_gallery.py` | OpenCLIP embeddings + fixed-K KMeans semantic clusters and HTML gallery | DEFER to V2; do not use as deletion or backup logic |

### Generated data and samples

- `organized_recent_photos/` contains a full run for 1,729 JPEG images, including symlink views, thumbnails, `.features.json`, JSON/CSV indexes and HTML.
- `organized_recent_photos_*_sample/` contains small test runs and named reverse-geocoding experiments.
- `favorite_export_20260420/` contains a copy-mode export of 361 selected items.
- `favorite_export_sample/` contains a symlink-mode export.
- `location_name_cache.json` is reusable reverse-geocoding cache data.
- `tmp_favorites.json`, `.DS_Store`, `__pycache__/`, generated galleries and exports are runtime/test artefacts, not source.
- The source sample tree contains 1,729 `.jpg` files and 54 `.mp4` files. Current Python/Swift image pipelines do not provide a complete video catalog.

There is no project-level `README.md`, dependency manifest, test suite, `.gitignore`, or git repository at this path. The folder is therefore not currently reproducible as an application build.

## Existing data formats

- `index.json` stores run metadata, dates, people, locations and photo records.
- `index.csv` stores flattened photo/export rows.
- `.features.json` stores image paths, capture dates/date sources, GPS, face counts, person IDs and people summaries.
- HTML favourites are browser `localStorage` state and downloadable JSON/CSV manifests.
- Full-size gallery assets are symlinks; originals are not moved by the organizer.
- Existing generated asset names are derived from SHA-1 of the path, not content. This is unsuitable as the permanent asset identity because paths can change.

## Reusable implementation

Keep or adapt the following ideas:

- date fallback chain and explicit `date_source`
- EXIF/GPS extraction shape
- cached reverse geocoding
- symlink-based virtual organization views
- thumbnail generation and lazy HTML gallery
- dHash/Hamming similarity and DSU clustering for candidate grouping
- browser favourites manifest/export flow
- explicit `--limit`, thresholds and no-reverse-geocode options for safe experiments

## Technical debt and risks

1. The organizer launches `swift` and uses macOS Vision/CoreML and `sips`; these must be behind platform interfaces.
2. Existing scans are output-directory builds, not resumable/incremental catalog scans.
3. Absolute paths are embedded in outputs and path-derived names are not stable across moves/remounts.
4. There is no authoritative SHA-256 content identity or destination verification.
5. dHash similarity is not exact duplicate detection and must not drive deletion.
6. Semantic KMeans clusters are fixed-K experiments, not persistent searchable labels.
7. Location clustering currently uses pairwise distance in `build_location_clusters`, which will not scale to very large libraries.
8. `build_pic_clip_gallery.py` removes its output directory when rebuilding; destructive output cleanup needs an explicit scoped safety layer.
9. `copy` options and favourite export modify filesystem state without the PhotoVault operation journal/quarantine model.
10. Existing outputs contain symlinks and cached thumbnails tied to a run; they are not the offline catalog.
11. There are no automated tests, dependency lockfiles, migrations, structured logs, or packaging configuration.

## macOS-specific dependencies

- Swift compiler/runtime
- Vision/CoreML feature prints
- CoreLocation reverse geocoding
- `sips`
- Apple filesystem/device commands are likely to be needed for stable volume identity, but must not leak into business logic

## Destructive or state-changing operations

- `organize_recent_photos.py --force` deletes and rebuilds its output directory.
- `build_pic_clip_gallery.py` removes its output directory during rebuild.
- `export_favorite_photos.py --mode copy` creates copies; symlink mode creates links.
- `group_test_pic.py --copy` creates copies.
- No existing script intentionally deletes original photographs, but there is no operation journal or undo system.

## Generated artefacts policy

Future `.gitignore` should exclude `.DS_Store`, `__pycache__/`, generated galleries/exports, feature caches, local SQLite databases, thumbnail caches and temporary manifests. Keep small deterministic fixtures under `tests/fixtures/` instead of committing real personal photographs.

## Audit conclusion

The prototype is valuable reference code, especially for metadata, thumbnails, GPS, face grouping and gallery UX. It should not be rewritten wholesale. Phase 1 should add a separate SQLite catalog and CLI for volume registration and incremental-safe file inventory, with no copy/move/delete functionality and no dependency on the existing macOS ML pipeline.
