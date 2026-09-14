# Smart Collage editor framework comparison

## Decision for the spike

Fabric.js is the primary engine candidate. It fits the current plain static web app, has the required object-transform and clipping primitives, and can be locally vendored. This is an engine decision, not a change to the PhotoVault document model.

| Criterion | Fabric.js 7.4.0 | Konva.js | Decision |
|---|---|---|---|
| Object selection, drag, scale, rotate | Native canvas objects and controls | Native node/event model | Both pass |
| Image clipping/masks | `clipPath`, including absolute clip paths | Clip functions / groups | Fabric is a closer fit for frame + image |
| Filters/effects | Image filters and opacity | Filters and cache-based rendering | Both pass; keep effects non-destructive in the document |
| Serialization | Strong, but framework JSON is not authoritative | Strong, but framework JSON is not authoritative | Adapter required for either |
| Existing static app integration | One local browser bundle, no build system required | Also possible | Fabric lower migration cost |
| Direct manipulation spike | Implemented at `/experimental/collage/fabric` | Not implemented | Fabric selected for evidence |
| License | MIT | MIT | Both acceptable |

TOAST UI Image Editor and `vue-fabric-editor` are reference material only. They are not foundations for this spike; no source was copied from them. miniPaint and Polotno are not adopted.

## Stop-gate recommendation

Keep the current editor available while this isolated spike is tested. If the spike passes the evidence checklist in `smart-collage-fabric-spike-report.md`, replace the custom interaction layer in one migration and remove the competing implementation rather than maintaining two editors indefinitely.
