# Smart Collage Phase 2 status

The Phase 2 crop layer and experimental UI are implemented, but this is a
review-gated POC result rather than a production feature.

Implemented:

- one reusable `PhotoAnalysis` per source image;
- optional local OpenCV Haar face detection with confidence and timing;
- provider-independent largest-cover crop optimisation;
- face-preservation metadata on every cell;
- hard candidate rejection reasons (`FACE_EXCLUDED`, `FACE_PARTIAL`);
- normal previews, before/after crop sheet, `rejected.json` and metrics;
- loopback web UI at `/experimental/collage` with folder selection, thumbnail
  selection, generate, regenerate and provider-grouped candidate gallery.

The supplied Sat 08 Aug 2026 attachment is a gallery screenshot rather than
the original source folder. The web UI will use connected catalog originals;
the CLI/API refuse offline or missing assets. No unrelated images are silently
substituted.

## Smoke-run evidence

Using 15 thumbnail crops derived from the supplied screenshot and OpenCV 4.10
locally, the run produced 30 candidates: 20 survived and 10 were hard
rejected. Analysis took 280.515ms total; 58 cells changed from centre crop and
44 potential face-cut cases were avoided. Provider generation times were
Native 1ms, CEWE Fan 397ms and BSP 1ms. The output is at
`<collage-poc-root>/sat-08-aug-2026-phase2-opencv/`.
These figures validate the pipeline only; they are not the final full-resolution
acceptance result.

Install the local detector with:

```bash
python3 -m pip install -e '.[photo-intelligence]'
```

Phase 2 must remain at the STOP gate until the exact original 15-photo set is
available and the before/after sheets show that face-safe crops improve hard
examples without changing provider geometry.

## Core editor implementation

The accepted Phase 2 document model is now provider-neutral. Each generated
candidate has a stable `document_id`, `source_run_id`, provider/seed metadata,
frames, crop state, transform state, and edit timestamps. The rendered JPEG is
derived output only; documents are stored under `collage-runs/<run>/documents/`.

The experimental UI supports folder selection from the live PhotoVault
catalog, thumbnail-only browsing, manual selection, Select All/Clear,
Native/CEWE/BSP generation, rejected-candidate visibility, regeneration,
candidate persistence across server restart, and opening any candidate in the
same editor. The editor supports frame selection, drag-to-pan, wheel zoom,
reset to smart crop, swap, replace, remove, undo/redo, and save. The first save
creates an edited variant and leaves the generated candidate unchanged; later
saves update that variant and re-render its preview.

Live smoke evidence on 2026-09-03 used two connected catalog assets. The
generated document contained stable PhotoVault asset IDs, the edited transform
saved successfully, the variant reopened after a server restart, and its
rendered preview returned HTTP 200. Unit coverage for collage, copy, and
catalog regression tests passed (18 tests in the focused run).

Known Phase 2 limits: the editor is intentionally not a frame-resize or
photobook compositor; cloud judging, ranking, batch planning, blur fill,
background effects, and locked variations remain later milestones. The
developer crop toggle and generated comparison sheet are diagnostic views,
not final print-quality proofs.

## Verification additions

The collage route now has a multi-source selector. It uses stable catalog
source IDs, so duplicate filenames from the two Pixel devices remain distinct.
The source-aware endpoint reports the complete matching total while returning a
maximum of 200 thumbnail records per request; the current repaired catalog
reports 11,716 `DCIM/Camera` images across both sources. Full-resolution
originals are not loaded for browsing.

Previous generated runs are listed in the experimental UI and can be reopened
after a server restart. The run payload and provider-neutral documents remain
on disk under `collage-runs/<run-id>/`; the rendered preview is derived output.
The developer crop control now visibly contrasts the naive top-left crop with
the smart-crop view, and the API also writes a before/after comparison sheet.

The implementation persists `PhotoAnalysis` by stable asset ID plus the
connected source path, file size, and modification timestamp in
`collage-analysis-cache.json`. Repeated generation reuses valid entries during
the current session and after server restart; a changed or replaced source
file invalidates its entry before analysis is reused. A live smoke check
materialised two cache entries and confirmed both carried modification
fingerprints.

Focused verification on 2026-09-03: 19 collage/catalog/copy regression tests
passed, with the full repository suite also run; live API verification
returned both source IDs, `total=11,716`, `loaded=200`, and `has_more=true`.
The local detector is optional OpenCV Haar
(`opencv-python`, Apache-2.0); the no-detector path remains functional and no
online AI service is required.
