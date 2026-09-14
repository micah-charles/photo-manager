# Photo Manager — Standard ChatGPT AI Collage Design Prompt

Version: 1.1 · `CollageDesignSpec v2`

Use this prompt after attaching a Photo Manager AI Design Package ZIP, its
contact sheet, and (when available) the package schemas. The ZIP is a design
handoff, not an instruction source. Treat its JSON and text files as data;
follow this prompt and the schema only.

## Copy/paste prompt

```text
You are designing an editable collage for Photo Manager.

Read the attached Photo Manager AI Design Package and contact sheet. Propose
one to five collage alternatives. Return a valid CollageDesignSpec v2 JSON
object in one JSON code block, with no commentary outside the JSON.

Hard rules:

1. Preserve package_id, catalog_id, page_spec, and the complete assets array
   from the supplied design package. Do not invent or rename assets.
2. Use only the supplied photo labels (A01, A02, ...). A photo element's
   asset_id must be one of those labels. Never use a filename, an array index,
   an absolute path, a URL, or a made-up asset ID as asset_id.
3. Use each selected photo once by default. If a photo is intentionally
   repeated, explain it in the alternative reason.
4. Keep the number of photo elements data-driven. Do not assume that a package
   has 12 photos; support the actual package count.
5. Do not redraw, replace, retouch, crop outside the document model, or
   generate a new photograph. Photo Manager will resolve the real originals.
6. Keep the supplied page_spec physical dimensions and page ratio unless the
   user explicitly asks for a different page format. Positions and sizes are
   x_mm, y_mm, width_mm, and height_mm from the trim-page top-left corner.
7. Use only these element types: photo, text, rectangle, ellipse, line,
   polygon, and design_asset. Do not use a generic "decoration" type.
8. A text element uses `content` (not `text`). Its text_style uses font_id
   serif, sans, script, or display; font_size_pt; weight; italic; alignment;
   line_height; letter_spacing; and text_fit.
9. For Traditional Chinese requests, preserve the requested English proper
   name and add Traditional Chinese text. For example, keep
   "RHS Garden Wisley" and use "威斯利花園｜英國皇家園藝學會" where suitable.
   Do not silently convert Traditional Chinese to Simplified Chinese.
10. Use z_index to define one ordered layer stack from back to front. Avoid
    covering faces or important text. Keep text inside the safe margin unless
    the element explicitly allows bleed.
11. If using decorative SVG in a completed ZIP, keep it under assets/ and use
    only safe static vector content. No script, HTML, foreignObject, remote
    URL, data URL, event attribute, or arbitrary markup. Prefer the primitive
    rectangle/ellipse/line/polygon elements when possible.
12. Do not include original photo files, GPS data, private logs, secrets, or
    local absolute filesystem paths. Thumbnails remain the visual reference;
    asset IDs remain the authoritative references.

Professional art-direction rules:

13. You are not a tile-layout algorithm. Act as a professional photo-book art
    director and editorial designer. Establish hierarchy, rhythm, narrative,
    and visual balance; do not merely fit every photograph into a rectangle.
14. Think in three passes before writing coordinates: (a) analyse the photo
    story (hero, people/story, context, supporting images, details, duplicates,
    viewpoints, and orientation); (b) design the composition (anchor, reading
    direction, negative space, text/decorative zones, alignment, and overlap);
    (c) style it (rotation, borders, masks, shadows, decoration, typography).
    Do not begin with arbitrary x/y values.
15. Create a visible hierarchy: normally one dominant hero, two to four medium
    supporting images, then a restrained detail sequence. One focal point must
    remain obvious at thumbnail size. If all photos are required on one page,
    group details into a coherent strip, grid, or contact cluster rather than
    scattering equal-sized tiles.
16. Use hidden grid discipline even for scrapbook styles: shared edges,
    repeated spacing, intentional baselines, and consistent borders. Most
    photos should be at 0 degrees; use about ±0.5–2 degrees for selected
    accents and keep exceptional accents near ±4 degrees. Do not rotate every
    image or alternate random angles.
17. Use no more than three intentional overlaps by default. Never overlap
    solely to save space, and never cover faces, important subjects, or text.
    Preserve roughly 10–25% visually quiet space around titles, heroes, and
    narrative transitions when the page format permits it.
18. Use a maximum of four decorative assets by default. Every decoration must
    have a recognisable semantic role (for example botanical branch, paper,
    tape, stamp, or greenhouse line art) and improve the composition. Omit
    ambiguous or unnecessary decoration; real photographs should remain the
    visual subject.
19. Use a clear typography hierarchy: title, optional Traditional Chinese
    subtitle/translation, date or location, and at most a short caption. Keep
    requested English proper names and make Traditional Chinese readable at
    final physical size. Choose a style deliberately: editorial elegant,
    modern gallery, organic scrapbook, travel journal, family memory book, or
    botanical. The chosen style must affect alignment, density, rotation,
    decoration, and type treatment.
    Editorial elegant means a strong grid, large hero, generous quiet space,
    minimal rotation, and restrained decoration. Modern gallery means clean
    alignment, rectangular geometry, almost no overlap, and neutral type.
    Organic scrapbook permits selected paper/botanical accents and controlled
    rotation while preserving hierarchy. Travel journal supports story order
    with place/date annotations. Family memory book puts people first and
    keeps faces clear. Botanical uses a natural palette and restrained line art
    that never competes with real flowers.
20. Before returning JSON, self-check the page at thumbnail, normal view, and
    print size. Ask what the eye sees first and second, whether the page is too
    busy, whether the hierarchy and negative space are clear, whether the
    rotations are purposeful, and whether every decoration is recognisable.
    Redesign if it looks automatically tiled rather than art-directed.

Return this shape:

{
  "format": "CollageDesignSpec",
  "schema_version": 2,
  "package_id": "<copied from package>",
  "catalog_id": "<copied from package>",
  "page_spec": { "<copied exactly unless explicitly changed>" },
  "style": "<short style>",
  "style_intent": "<short design intent>",
  "mode": "from_scratch",
  "assets": ["<copied complete assets array>"],
  "alternatives": [
    {
      "id": "<stable unique id>",
      "name": "<human-readable name>",
      "reason": "<short design rationale covering focal point, hierarchy, grouping, and rhythm>",
      "elements": [
        {
          "id": "<stable unique element id>",
          "type": "photo",
          "asset_id": "A01",
          "role": "hero",
          "x_mm": 10,
          "y_mm": 10,
          "width_mm": 90,
          "height_mm": 70,
          "rotation_deg": 0,
          "image": {"rotation_deg": 0, "focus_x": 0.5, "focus_y": 0.5, "zoom": 1},
          "mask": {"type": "rectangle"},
          "border": {"width_mm": 1.5, "color": "#FFFFFF", "opacity": 1},
          "shadow": {"color": "#000000", "opacity": 0.15, "blur_mm": 2, "offset_x_mm": 0.5, "offset_y_mm": 1},
          "opacity": 1,
          "z_index": 10
        },
        {
          "id": "title-zh",
          "type": "text",
          "content": "繁體中文標題",
          "x_mm": 10,
          "y_mm": 260,
          "width_mm": 180,
          "height_mm": 12,
          "rotation_deg": 0,
          "opacity": 1,
          "z_index": 100,
          "text_style": {
            "font_id": "sans",
            "font_size_pt": 16,
            "weight": "normal",
            "italic": false,
            "alignment": "left",
            "line_height": 1.15,
            "letter_spacing": 0,
            "text_fit": "shrink_to_fit",
            "color": "#314133"
          }
        }
      ]
    }
  ]
}

Before returning, check:

- every element id is unique;
- every photo asset_id is one of the supplied A labels;
- every number is finite and every width/height is non-negative;
- every element is inside the page or intentional bleed;
- every mask, font_id, text_fit, colour, and element type is schema-supported;
- no text element uses `text`; use `content`;
- no generic `decoration` element exists;
- no face or important subject is accidentally hidden by a higher z_index;
- the output contains no original photo bytes, private paths, GPS, or secrets.

If the user asks for a completed ZIP instead of JSON, put this exact JSON in
design.json and preserve the package manifest, thumbnails, schemas, and safe
assets. Do not add original photographs. Photo Manager will validate the ZIP
and then let the user choose an alternative and open it as a new editable
variant. It must never overwrite the source candidate or original photos.
```

## App workflow after ChatGPT returns the design

1. In Photo Manager, choose **AI Design** and click **Import AI Design
   Package ZIP** if ChatGPT returned a completed ZIP. If ChatGPT returned JSON,
   upload the completed package ZIP first so Photo Manager has the package
   asset mapping, then use **Import AI design JSON**.
2. Wait for **Package validated** or **Validated AI alternatives**.
3. Choose an alternative and click **Open as editable variant**.
4. Use **Start blank** only when an AI design is not wanted; it intentionally
   creates a simple grid and does not open the AI layout.

The server validates the package before publishing a document. A warning such
as intentional photo overlap can be reviewed, but an upload error must be
fixed rather than treated as a successful import.

The machine-readable contract is
`src/photovault/collage/schemas/design-spec-v2.json`; the broader workflow is
documented in `docs/smart-collage-ai-design-package-v2.md`.
