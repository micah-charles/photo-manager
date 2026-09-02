# PhotoVault Phase 0 acceptance matrix

This matrix records the current implementation against the supplied Phase 0
brief. “Verified” means there is a local automated or rendered check; it does
not imply that an external device or operating system has been tested.
The latest local evidence is from the current feature branch (with subsequent local
source changes tracked on the same branch).

| Area | Current evidence | Status |
| --- | --- | --- |
| Photo-first Home and grouped navigation | `src/photovault/ui/spec.py`, live dashboard screenshot, native Qt sidebar icons | Verified locally |
| Library thumbnail browsing | `PhotoGrid`, cached previews, pagination, filters, sorting, selection count, viewer and context actions; external 6,674-item catalog capture | Verified locally |
| Viewer and inspector | `photo_viewer_page.py`, metadata/location/protection details, previous/next navigation | Verified locally |
| Collections and albums | Live folder/album cards, cached covers, click/double-click/keyboard routing to Library; UI regression coverage | Verified locally |
| Favourites | Library smart-view handoff and persistent catalog annotation tests | Verified locally |
| People, Places, Categories, duplicates | Live catalog-derived views, advisory metadata boundaries, empty states and browse routing | Verified locally; enrichment remains data-dependent |
| Android connection and folder selection | Wi-Fi Companion discovery worker, persistent identity, live folder picker, media filter, advanced settings disclosure | Verified by Qt smoke tests; live phone UI capture pending |
| Android transfer progress and completion | Background worker, atomic verified import, durable import-batch history, batch fsync, cancellation/resume messaging, progress/speed/ETA tests, completion actions | Verified by source/Qt tests; live transfer regression pending |
| Metadata preservation | Verified destination is parsed after size/SHA verification; EXIF dimensions/date/GPS remain catalog data and originals are untouched | Verified by regression test |
| Backup safety | Partial-file import, hash/size verification, atomic rename, conflict rejection, no source deletion propagation, reversible quarantine | Verified by source-import/copy/quarantine tests |
| Storage and backup health | Live drive cards, backup-set health summary, advanced technical tables | Verified locally |
| Responsiveness | Scan, Android, transfer, thumbnails, classification, recovery and operations use worker/thread paths | Verified by code and UI tests |
| macOS packaging | `scripts/build_app.py --clean`, arm64 `dist/PhotoVault.app`, bundled `--help` smoke test | Verified locally |
| Windows packaging | Cross-platform provider, CI matrix, Windows package smoke test and artifact upload are defined | Awaiting Windows runner result |
| Visual review deliverables | `scripts/capture_ui_review.py`, 16 external screenshots, and source/package artifacts | Verified locally |

The current local verification total is 105/105 tests. The latest deterministic
Qt capture contains 16 pages. The corresponding external-drive delivery files are
`/Volumes/ExtremePro/PhotoVault-UI-Review-20260901/photovault-source-50de0da.zip`
and
`/Volumes/ExtremePro/PhotoVault-UI-Review-20260901/photovault-ui-review-50de0da.zip`.

## Remaining gates

1. Run the GitHub Actions Windows job and inspect the uploaded executable on a
   real Windows host.
2. Connect the Pixel Companion and capture connected, active-transfer,
   cancellation, and completion UI states against a live transfer.
3. Replace remaining incremental/card-polish work only after those runtime
   gates are green; do not treat mock data or deterministic UI fixtures as proof
   of a live device transfer.
