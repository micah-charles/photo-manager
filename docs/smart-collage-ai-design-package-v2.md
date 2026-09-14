# Smart Collage Creator Mode

Creator Mode is the manual Photo Manager ↔ ChatGPT interchange path:

```text
Topic → Section → select photos → Export design package
      → ChatGPT edits design.json → Import / validate → open new editable variant
```

The app remains responsible for resolving real catalog assets and rendering them. ChatGPT only proposes geometry and presentation; it never receives an automatic API upload and it never replaces an original photograph.

## Package contents

An exported v2 ZIP contains:

- `manifest.json` — catalog-scoped package identity, `A01` photo labels, page spec, and optional safe decorative assets.
- `design.json` — a `CollageDesignSpec` v2 request/response document in millimetres.
- `contact-sheet.jpg` and `thumbnails/A01.jpg…` — visual references for manual ChatGPT hand-off.
- versioned schemas, `CHATGPT-INSTRUCTIONS.md`, and a short README.
- `current-layout.json` in improve-existing mode.

Original photographs, GPS metadata, local absolute paths, and arbitrary HTML/SVG are not included. The absolute catalog location remains a local lookup concern and is never trusted from an imported file.

Decorative artwork is optional. Only SVG, PNG, and WebP members under `assets/` are accepted; SVG is parsed through an allow-list before it is served to Fabric. The importer rejects traversal, scripts, external URLs, duplicate IDs, unknown assets, non-finite numbers, and unsupported versions.

## Geometry and editing

`page_spec` is the physical source of truth. Photo, text, decoration, and design-art elements share one ordered `elements` array. Positions and sizes use `x_mm`, `y_mm`, `width_mm`, `height_mm`; frame rotation is independent from the photo crop's image rotation, focus, and zoom. The browser uses a deterministic display scale, while high-resolution PNG export converts the same document to the requested DPI and reloads connected originals.

Guides are a DOM overlay only. They are not Fabric objects and therefore cannot leak into saved documents or PNG exports.

## Reference fixture

`examples/kew-gardens-ai-design-v2.json` is a catalog-neutral, 300 × 300 mm reference with 12 explicit photo slots, title/date/caption text, layer order, masks, borders, shadows, rotation, and text-fit rules. Its `example_asset_*` IDs are placeholders for the currently selected catalog assets; it contains no personal photographs.

The older `examples/kew-gardens-ai-design-v1.json` remains available to verify the explicit v1 adapter.

## Verification checklist

The regression suite covers v2 package upload, SVG sanitisation, managed decorative-asset serving, AI validation, document conversion, and save-as-new-variant. Browser verification covers:

1. Topic → Section selection and exact selected-photo count.
2. Start Blank → one-renderer editable canvas with 18 layers.
3. Kew Gardens fixture → visible photos, text, and decoration.
4. Layer selection → inspector enablement; text controls only for text layers.
5. Border width, frame rotation, image zoom, image rotation, text editing, guides, and undo.
6. Responsive layout → inspector remains available below the canvas on narrow windows.

Known boundary: the fixture's vector leaf is an editable approximation, not a reconstruction of raster watercolour texture. High-resolution export requires connected originals; offline thumbnails are never silently advertised as original-quality output.
