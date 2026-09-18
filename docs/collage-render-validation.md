# Collage render-space validation

Collage design imports use two validation stages:

1. `validate_and_repair_design_spec()` validates the AI-facing DesignSpec in
   millimetres. Its text measurements are deterministic estimates used for
   schema safety, transformed page bounds, collision checks, approximate
   fitting and bounded repairs.
2. The shared browser `renderDocument()` renderer creates the Fabric objects,
   waits for fonts and assets, applies the existing safe-area/font repairs,
   and then validates the final Fabric geometry. Browser font rendering and
   Fabric's public `setCoords()` / `getBoundingRect()` results are authoritative
   for the final composition report.

Hard geometry errors block publication; a broken alternative is never silently
opened as an editable document. The editor preview and PNG export both call
this same renderer and therefore share the same render-space warnings. The validator measures photo frame
objects, not the oversized clipped photo image, and does not include selection
handles or other editor chrome. It reports problems but does not move artwork;
the only automatic changes remain the existing bounded safe-area and
shrink-to-fit repairs.

Current render-space warning codes include:

- `FABRIC_TEXT_DECLARED_BOX_OVERFLOW`: actual text bounds extend beyond the
  declared, rotation-aware text box. Existing `FABRIC_TEXT_OVERFLOW` warnings
  are enriched with the actual bounds instead of being duplicated.
- `FABRIC_TEXT_PHOTO_COLLISION`: actual text and photo-frame bounds have a
  meaningful intersection.
- `FABRIC_TEXT_COVERED_BY_PHOTO`: the same actual intersection is behind a
  foreground photo according to z-order.
- `FABRIC_TEXT_PHOTO_CLEARANCE`: text does not intersect a photo, but the gap
  is at most 2 mm at the document's 4 px/mm logical scale.
- `FABRIC_TEXT_TEXT_COLLISION`: significant intersection between unrelated
  visible text objects.

Intentional overlap must be explicit in the element. Set
`allow_photo_overlap: true` to allow an intentional text/photo or photo/photo
overlap, or `allow_text_overlap: true` for a deliberate text composition. Both
default to `false` and are separate from `allow_bleed`; bleed controls page
boundaries, not composition overlap. The renderer keeps its existing 2 mm
compatibility threshold; new AI layouts prefer approximately 3 mm clearance.
