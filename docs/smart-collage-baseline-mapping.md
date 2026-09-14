# Sat 08 Aug 2026 baseline mapping

The supplied reference is a PhotoVault gallery screenshot held outside the
repository. It contains 28 visible thumbnails under **Sat, 08 Aug 2026**. The PhotoVault
catalog database did not resolve that date, but a direct read-only scan of the
mounted camera exports found the corresponding original files.

The Phase 2 smoke run therefore used 15 explicitly labelled crops derived from
the Sat 08 Aug row, not unrelated images. Source paths and camera filenames
are intentionally omitted from this public repository:

| baseline item | original source | status |
|---|---|---|
| `sat-08-00` … `sat-08-14` | external camera fixture, identified only by stable test labels | visually matched |

The CLI POC has now been rerun against 15 full-resolution originals in an
external fixture directory.
The catalog still has no asset IDs for these files, so this run is a verified
source-folder experiment rather than a catalog/API acceptance run. The next
integration step is to register these originals in the catalog and expose them
through the existing asset-ID original route.
