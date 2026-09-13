# Smart Collage third-party notices

This document is the license gate for the editor-engine spike. It records the exact dependency and whether Photo Manager copies it into the distributable.

| Component | Repository / source | Exact version | License / copyright | Vendorized? | Attribution |
|---|---|---:|---|---|---|
| Fabric.js | [fabricjs/fabric.js](https://github.com/fabricjs/fabric.js) | 7.4.0 | MIT; copyright 2008–2015 Printio and 2016–present Andrea Bogazzi, Shachar Nen and contributors | Yes, unmodified browser bundle at `src/photovault/web/static/vendor/fabric/index.min.js` | `src/photovault/web/static/vendor/fabric/LICENSE` is retained |
| CEWE layout | [vincedarley/cewe-layout](https://github.com/vincedarley/cewe-layout) | Existing implementation | MIT | Existing approved subset only | Existing `src/photovault/collage/vendor/CEWE_LAYOUT_LICENSE` is retained |
| BSP | [bjdekker/photo-collage](https://github.com/bjdekker/photo-collage) | Reference only | Upstream license not sufficiently clear for redistribution | No | Photo Manager BSP is a clean-room independent implementation; no upstream source copied |
| Native | Photo Manager | N/A | Photo Manager-owned | N/A | No third-party notice required |

## Excluded from this architecture

Polotno, commercial editor SDKs, cloud editing APIs, unknown repositories, and ML weights with unclear redistribution terms are not dependencies of this spike.

## ML gate

The editor spike does not add an inference runtime or model weights. Any future face, subject, or saliency model must record runtime license, weight license, redistribution, commercial-use, and attribution terms separately before it is downloaded or vendorized.

## Security and provenance

Fabric was pinned rather than loaded from a CDN. The bundle is a browser distribution from the npm package and was not modified. The version and advisory status must be rechecked when upgrading; `npm audit` output is recorded in the spike report.
