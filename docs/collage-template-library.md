# Adaptive photo-book template library

The existing topic/section → design validation → editable Fabric variant workflow
is unchanged. `collage_template_library.js` supplies the creative layer as a pure,
versioned engine; `collage_sample_workflow.js` adapts the existing editor controls.
Output remains CollageDesignSpec v2. No new storage or rendering infrastructure.

## Twelve composition families

| Family | Distinct spatial grammar |
| --- | --- |
| Kew Interlocking Scrapbook | Protected anchor cards interlock above a loose ribbon of smaller prints; title lives in the footer. Additional photos subdivide support regions. |
| Editorial Opening | A dominant opening image, narrow sidebar and separate closing band establish a magazine-like reading hierarchy. |
| Two Perspectives | Two staggered anchors occupy opposite ends of parallel tracks, each with its own photographic trail. |
| Architectural Spine | A tall central anchor connects staggered wings of details; the spine changes axis on wide pages. |
| Family Constellation | One central portrait is surrounded by unequal satellite clusters, rather than a top row of heroes. |
| Scenic Horizon | A full-width establishing image separates two bands of supporting moments. |
| Film Diary | Photo elements follow capture order through dark film lanes. Hero choices expand individual frames without reordering the sequence. |
| Story Chapters | Three episodes each have an opening anchor and smaller scenes. Wide pages use columns; tall pages use bands. |
| Travel Notebook | Alternating picture clusters and editable narrative blocks form an offset reading path. |
| Quiet Gallery | One generous image has a deliberate narrative margin; three smaller study clusters close the page. |
| Woven Mosaic | Interlocking rectangular regions subdivide at several scales while preserving the larger anchors. |
| Botanical Fieldnotes | A central chain of specimens sits between two detail ribbons and editable fieldnotes. |

The unchanged original Kew reference fixture remains a separate, exact-12-photo
option. It is not substituted for any adaptive family.

## Use in the editor

1. Choose a family from **Sample**, or choose a recommended family below the source controls.
2. Choose a topic and section, then a page size. Alternatively, use **Open selected sample**
   with the photos in the current document.
3. Keep **Template / existing roles**, or select one hero, hero + sub-hero, or
   multiple heroes (up to four in the UI).
4. Click **Generate from selected section**. Review crops in Crop mode, edit the
   text as needed, then **Save variant** to retain the design and source metadata.

Generation creates a new variant; it does not replace the source collage.
All section assets must finish loading. Missing metadata blocks generation rather
than silently omitting photographs. Source request guards discard stale responses,
and generation disables source controls to prevent duplicate submissions.

## Adaptation and semantic recommendations

- Adaptive families accept **10–60 distinct photos**, placing each exactly once in
  an editable photo element. Counts outside that range are rejected, not truncated.
- Seven existing physical presets are supported: 20/25/30 cm square, A4 portrait
  and landscape, and 20 × 30 / 30 × 20 cm. The pure engine also supports the existing
  spread convention (width describes one page) with a central binding gutter; the
  current sample UI selects single-page presets.
- `architecture_journey`, `scenic_hero`, `sequence_journey`, `family_memory`,
  `detail_mosaic` and `travel_scrapbook` rank compatible families. Available hero,
  subhero, supporting and detail roles influence placement.
- For the current matching section, the adapter reuses document composition
  metadata and title/subtitle/caption. Otherwise it uses section metadata, with
  section-title keywords as a fallback hint. It does not search all saved project
  variants for earlier analyses of another section.
- Non-sequence families use minimum-cost assignment based on oriented aspect
  ratio, crop retention, resolution, ratings and optional quality/face metadata.
  Manual heroes are placed in the largest slots; no fourth hero is dropped.
- Film Diary and Story Chapters retain capture order (stable source order when
  times are absent), adapting frame prominence for selected roles.
- Automatic placement is a metadata/fit recommendation, **not visual recognition
  or an aesthetic judgement**. Review faces and important details before printing.

Title defaults to 27 pt, subtitle to 12 pt, and caption/fieldnotes to 11 pt. Text
uses the existing `wrap_and_shrink` contract and now renders through Fabric
Textbox for actual wrapping; other text-fit modes keep their existing behavior.
These are requested sizes: long text can still shrink to fit its reserved region.
Dense pages warn when frames become small; crop warnings direct the user to Crop
mode. No automatic title writing or external AI upload is added.

## Verification

Run from the repository root:

```sh
node tests/collage_template_library.test.cjs
PYTHONPATH=src python3 -m unittest tests.test_collage_template_library tests.test_collage_editor_contract
```

- 5,544 generated layouts check all-photo identity, finite/on-page geometry,
  spread gutters, roles and chronology across families, counts, presets and source
  orientation distributions. Additional regressions check the fourth manual hero,
  missing/duplicate IDs, semantic recommendations and distinct spatial plans.
- 336 cases run through the actual Python validation, conversion and document-save
  contract, checking that every source photo remains editable and present once.
- `tests/render_collage_templates.cjs` is an opt-in browser harness using the
  production renderer and local photo metadata. It saves 84 actual rendered pages
  and seven family comparison boards (10/15/20 photos on A4 portrait/landscape,
  plus 12 photos on square pages). It never saves documents to the live catalog.

```sh
PLAYWRIGHT_MODULE=/path/to/playwright node tests/render_collage_templates.cjs /path/to/photos.json /path/to/review-output
```

Visual review on 2026-09-22 checked distinct page silhouettes, text wrapping and
photo coverage. The 84-page run had no JavaScript errors, failed elements or
renderer warnings. Private source photos and review renders are not committed.
This is sampled visual evidence, not a guarantee that every count or crop will
be aesthetically optimal; the editor retains manual hero and crop control.
