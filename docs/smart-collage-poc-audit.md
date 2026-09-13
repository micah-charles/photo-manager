# Smart Collage POC audit

Date: 2026-09-03  
Scope: `/Volumes/ExtremePro/project/codex/photo-manager-github`

## Reusable existing components

The POC is isolated under `src/photovault/collage/`. It reuses the existing
Pillow-based metadata reader for dimensions and EXIF capture time, and follows
the repository's existing optional-dependency policy. The existing thumbnail
cache and gallery remain unchanged; POC previews are written only to an
explicit output directory. Catalog, backup, import, desktop UI and web routes
are not part of this opt-in experiment.

## Dependencies and constraints

Pillow is already an optional dependency in `desktop` and `photo-intelligence`;
no new package was added. The POC uses Pillow for image decode, resize, crop,
sharpness proxy and JPEG output. It has no cloud AI, model weights, OpenCV or
ONNX requirement. EXIF parsing is reused from `photovault.catalog.metadata`.

## Layout approaches evaluated

The native provider is a deterministic grid baseline. The BSP provider is an
original clean-room recursive binary-space-partition implementation, because
the upstream `bjdekker/photo-collage` repository does not declare a completed
licence. The `cewe-genetic` provider now runs the upstream
`vincedarley/cewe-layout` Fan genetic algorithm through an adapter; its small
MIT-licensed algorithm subset is vendored with attribution and its license.

Only the CEWE algorithm dependency subset (`base.py`, `evaluator.py` and
`fan_layout.py`) is vendored; the CEWE UI and photobook workflow are not. The
upstream MIT notice is retained in `src/photovault/collage/vendor/`.
Existing open-source landscape research is recorded in
`docs/OPEN_SOURCE_LANDSCAPE.md`; the BSP source remains clean-room because its
upstream licence is unresolved.

## Phase 1 boundary

The command generates 30 structured candidates (10 per provider: Native,
CEWE Fan genetic algorithm and BSP), renders each
individually, writes a labelled contact sheet and saves JSON metadata. It does
not perform face detection, saliency, hard rejection, ranking, batch planning,
database persistence or normal UI integration. Those are later phases gated on
visual review.
