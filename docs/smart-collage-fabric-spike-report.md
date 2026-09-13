# Smart Collage Fabric.js spike report

## Scope

This is an isolated editor-engine spike, not a production rewrite. Open it at:

`http://127.0.0.1:8767/experimental/collage/fabric`

It loads a real candidate from the existing `/api/collage/runs` catalog. The adapter keeps `CollageDocument` as the source of truth and maps frames to Fabric image/outline objects. Fabric JSON is never saved.

## Evidence checklist

- [x] Local pinned Fabric.js bundle, version 7.4.0.
- [x] Existing candidate gallery/run selection remains available.
- [x] Open and reload a real structured candidate.
- [x] Layout mode: select, move, resize, and rotate frame outlines using Fabric controls.
- [x] Crop mode: select and pan image inside a fixed clipping frame; wheel zoom is supported.
- [x] Replace by photo panel/drop target, reset crop, rotate image.
- [x] Opacity, border width/colour, rectangle/rounded/circle mask, layer order.
- [x] Undo/redo and save as an editable variant through the existing document endpoint.
- [ ] Browser visual evidence on every operation (manual stop-gate run still required).
- [ ] Full semantic round-trip assertion against a fixture (next test increment).

## Known spike limits

This first spike intentionally does not add full effect controls, locking UI, two-photo swap gestures, or a complete responsive editor shell. It demonstrates whether Fabric can replace the custom transform mechanics without corrupting PhotoVault's document format.

## Dependency check

Fabric 7.4.0 is pinned and locally served. Run the project-side equivalent before a production adoption:

```sh
npm audit --omit=dev
```

The audit run for Fabric 7.4.0 reported 0 info, 0 low, 0 moderate, 0 high, and 0 critical vulnerabilities.

The spike has no npm runtime dependency in the Python project; the vendored bundle and retained MIT notice are the reproducible browser artifact. A production migration should add a lockfile/build provenance check rather than silently updating this file.

## Recommendation

Proceed to browser validation first. Do not remove the existing custom editor until save/reopen visually reproduces a real candidate and the adapter has a fixture-level round-trip test.
