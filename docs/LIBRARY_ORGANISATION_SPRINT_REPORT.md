# PhotoVault library organisation sprint

## Verified implementation status

The catalog now has additive migration support for source provenance, source
display-time offsets, events, tags, manual places, review status, and ratings.
The Library query uses the same filters for listing and counting, hides rejected
and hidden items by default, and keeps an explicit opt-in to show them.

The desktop UI currently exposes:

- Library source, event, tag, place, review, rating, and hidden-item filters;
- batch review status, rating, Event, Tag, and Place actions;
- Review queues with keyboard shortcuts in the Viewer (`P`, `R`, `H`, and arrows);
- Event and Tag creation and filter navigation;
- manual Place creation;
- Source listing, local folder/SD registration, background scan, and display-only
  time-offset editing;
- Viewer organisation metadata inspection;
- source-aware unified Timeline display time while retaining raw capture time.
- Timeline day grouping and a cross-source filter for chronological browsing.
- Paginated Library and Timeline browsing, with explicit page-size and
  Previous/Next controls so large catalogs are not truncated to the first page.
- Manual Places table with select-to-edit, update, delete, and Library assignment.
- Durable import-batch history with per-run source/destination identity,
  lifecycle status, verified counters, byte totals, and Activity-page display.

All organisation actions are catalog-only. They do not move, rename, delete, or
rewrite original media. Existing verified import and backup safety boundaries are
unchanged.

## Verification evidence

```text
PYTHONUNBUFFERED=1 PYTHONWARNINGS=ignore QT_QPA_PLATFORM=offscreen \
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*.py'

Ran 104 tests
OK
```

The deterministic Qt capture harness covers 16 pages. The latest screenshots
are stored outside the repository at:

`/Volumes/ExtremePro/AIWorkspace/PhotoVault-VisualQA/screenshots`

The catalog fixture used for visual QA is a copy under
`/Volumes/ExtremePro/AIWorkspace/PhotoVault-VisualQA`; the original regression
catalog is not opened in write mode by the capture process.

The current macOS release smoke check also passes:

- PyInstaller 6.22.2 produced `dist/PhotoVault.app` for arm64;
- the bundled executable responds to `--help`;
- the bundle contains the native macOS Android MTP helper;
- the Windows packaging path remains platform-neutral in Python, but requires
  an actual Windows runner for final executable and removable-drive validation.

## Remaining work before final completion

The master brief still requires a final product pass for multi-source import
batch controls/resume UX, bulk metadata UX polish, accessibility checks,
cross-platform packaging validation, and a final end-to-end acceptance
walkthrough on representative media. These items remain deliberately open;
the green regression suite is not treated as proof that the entire brief is
complete.
