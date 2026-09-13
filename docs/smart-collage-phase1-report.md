# Smart Collage Phase 1 comparison

Date: 2026-09-03

## Baseline

The supplied baseline was the PhotoVault gallery screenshot for **Sat, 08 Aug
2026**. The attachment contained the gallery screenshot only, not the original
photo files or an accessible catalog folder. For this run, 15 visible photo
thumbnails were cropped from that screenshot and used as the identical input
set for every provider. This is suitable for comparing geometry and provider
behaviour, but not for judging full-resolution crop quality. A rerun against
the original files is still required for a final visual decision.

Output: `reports/smart-collage-poc/sat-08-aug-2026/`

## Results

| Provider | Algorithm | Licence | Direct code reuse? | Candidates | Generation time | Observed strengths | Observed weaknesses |
|---|---|---|---:|---:|---:|---|---|
| Native | deterministic grid / shuffled assignment | PhotoVault | No | 10 | 0.000s | predictable, complete coverage, easy to maintain | repetitive grid geometry; no hero weighting |
| CEWE Fan | upstream Fan genetic algorithm with slicing trees | MIT | Yes, vendored subset with attribution | 10 | 0.401s | genuinely varied weighted layouts; hero-sized photos; strongest exploration | several layouts leave visible unused space because upstream preserves source aspect ratios |
| BSP | clean-room recursive BSP based on `bjdekker/photo-collage` README | upstream licence unresolved; no source copied | No | 10 | 0.000s | fills canvas, varied composition, fast | no content awareness; some cells can still be visually awkward |

Total: **30 candidates**, all rendered with the same 1200×800 canvas and 12px
gutter. The full run took 1.663s on the local machine, including image decode
and JPEG rendering.

## Phase 2 implementation note

The content-aware crop layer now uses one cached `PhotoAnalysis` per source
photo. Face detection is provided by optional CPU-local OpenCV Haar cascades
(Apache-2.0 OpenCV runtime; the macOS arm64 wheel measured 54.8 MB in this
environment and the cascade is shipped by the package), with an
explicit unavailable state when the optional dependency is not installed. The
Phase 2 UI and API use the same optimiser for all providers. No face detection
is run per candidate.

## Recommendation

Keep all three as candidate generators for the next experiment. Use CEWE Fan
for higher-variance editorial candidates, BSP as the coverage-focused fallback,
and Native as the deterministic baseline. Do not add AI scoring yet: first
rerun this exact comparison on the original 2026-08-08 files, then add
face-safe cropping and hard rejection around the providers.
