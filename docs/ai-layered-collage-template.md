# AI Layered Collage Template v2

Photo Manager supports the ordinary coordinate-based `CollageDesignSpec v2`
and an optional `layered-template` capability. The extension is deliberately
backwards compatible: packages without the capability use the existing
renderer and are not required to contain any template artwork.

## ZIP contract

```text
manifest.json
design.json
template/foreground.png       # required, RGBA, same aspect ratio as page
template/background.png       # optional, PNG, same dimensions as foreground
template/masks/A01.png        # one mask for every declared slot
template/masks/A02.png
preview/reference.png         # optional, never used as a photo
```

The manifest declares the capability and the slot geometry:

```json
{
  "format": "PhotoManager AI Design Package",
  "schema_version": 2,
  "capabilities": ["layered-template", "transparent-photo-slots"],
  "template": {
    "foreground": "template/foreground.png",
    "background": "template/background.png",
    "masks": {"A01": "template/masks/A01.png"},
    "slots": {
      "A01": {
        "role": "hero",
        "x_mm": 24, "y_mm": 42,
        "width_mm": 130, "height_mm": 95
      }
    }
  }
}
```

`design.json` still contains complete photo asset objects and one or more
alternatives. A photo element must identify its slot with `slot_id` (or use an
`asset_id` equal to the slot label, such as `A01`). The importer resolves that
label to the real catalog `asset_id`; it never opens a path supplied by an AI
response.

Masks use white/luminance = photo visible and black = clipped. The server
converts each mask to an alpha-only managed PNG because Fabric clip paths use
alpha, not luminance. This keeps irregular, circular, rotated and edge masks
consistent in the editor, preview PNG and high-resolution PNG export.

The foreground is not an image placeholder. Its pixels must be transparent in
every declared photo aperture. An opaque white foreground, missing aperture,
wrong dimensions, non-RGBA foreground, traversal path, or unsupported file is
rejected with a slot-specific error. Intentional occlusion can be declared by
`allowedForegroundOcclusion` with an explicit `max_fraction` and optional
normalised local `regions`; it is never silently ignored.

## Compositing order

The imported `CollageDocument v2` contains locked template layers in the same
ordered `elements` array as every other layer:

1. page/background colour;
2. optional template background;
3. photo slots sorted by `z_index`, using the real catalog originals and the
   existing focal-point/zoom crop model;
4. editable text and vector decorations;
5. locked transparent template foreground.

The photo itself remains selectable in Crop mode. The foreground/background
are selectable only from Layers when unlocked deliberately; they are locked by
default. Template masks are applied to the photo object, so moving or zooming a
photo cannot move the aperture.

## Editor debug tools

For a layered document the editor shows Template controls for slot boundaries,
slot IDs, mask overlays, and temporarily hiding the foreground. Debug overlays
are marked `excludeFromExport` and are never included in saved documents or
exports.

## Safe generation prompt

Tell the design model:

> Use only A-labels from `design.json`; never invent, redraw, retouch, or
> embed photos. Return `CollageDesignSpec v2` JSON and keep each photo mapped to
> exactly one declared slot. Preserve the supplied page dimensions and mm
> coordinates. Treat `template/foreground.png` as a transparent RGBA overlay,
> not as a white canvas. Do not replace it with a screenshot or JPEG. Keep
> faces/persons clear of intentional overlaps, preserve the declared focal
> point when choosing crops, and explain any deliberate foreground occlusion in
> metadata. Do not return HTML, SVG markup, scripts, remote URLs, or local
> filesystem paths.

## Verification

The repository tests cover transparent/opaque apertures, mask normalisation,
dimension and traversal rejection, synthetic film-strip masks, document layer
ordering, editor debug controls, export wiring, and ordinary v2 package
compatibility. Test fixtures use generated coloured rectangles only; no private
photo files belong in Git.
