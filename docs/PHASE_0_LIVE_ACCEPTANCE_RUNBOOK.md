# PhotoVault Phase 0 live acceptance runbook

This runbook covers the two checks that cannot be proven by the local Qt test
suite: a real Android Companion transfer and a real Windows package smoke test.
It is intentionally read-only on the phone. Put the catalog, logs, and copied
media on an external drive.

## Pixel Companion transfer

1. On the Pixel, open PhotoVault Companion, choose a sharing duration, and keep
   the sharing notification active. Keep the Mac and phone on the same Wi-Fi.
2. Start PhotoVault with an external catalog:

   ```bash
   cd /path/to/photo-manager
   PYTHONPATH=src .venv/bin/python -m photovault.ui \
     --catalog /path/to/live-acceptance.db
   ```

3. Open **Android Devices**, enter the current Companion URL/token, and press
   **Connect**. Confirm the device identity and folder inventory.
4. Select `DCIM/Camera`, first choose a small test limit, and choose a
   destination under `/path/to/backup-root`. Verify the plan before starting.
5. Start the transfer and record the live file count, bytes, elapsed time,
   average speed, interval speed, and ETA. Cancel once during the small test;
   confirm the UI says it is safe to resume.
6. Start the same profile again. Confirm already-imported files are skipped,
   partial files resume safely, and the final result is shown in **Operations**.
7. Verify the catalog batch history from Terminal:

   ```bash
   PYTHONPATH=src .venv/bin/python -m photovault.cli \
     --catalog /path/to/live-acceptance.db \
     android import-batches --limit 20
   ```

8. Compare a sample of destination SHA-256 values and metadata. Originals on
   the phone must remain unchanged; the app must not rewrite EXIF/XMP/GPS.

## Windows package smoke test

Run the existing CI `packaging-smoke` job on a Windows runner, then verify the
uploaded artifact on an actual Windows host:

```powershell
dist\PhotoVault\PhotoVault.exe --help
```

Open the app with a catalog on a removable destination, register a folder,
scan it, browse thumbnails, and confirm the Windows volume provider reports
connected/offline state without changing the source folder.

## Desktop organisation smoke test

With the macOS app open and the external regression catalog selected:

1. Open **Collections**. Single-click an album to select it; double-click the
   album (or press Enter) and confirm PhotoVault opens **Library** filtered to
   that album. An empty album should still open Library and show an explanatory
   empty-state message.
2. Double-click a Library thumbnail and confirm **Photo Viewer** opens.
3. In **Timeline**, apply a date range and source filter, then open an item in
   Viewer. Create an Event from the selected dates and confirm its members
   appear in Event Detail.
4. In Library, select multiple items and test Add Tag, Set Place, Add Person,
   Add to Collection, Pick/Reject, Favourite, and rating. Confirm the result
   appears in the relevant filter without changing the original files.
5. Open **Review**, **People**, **Places**, **Tags**, **Categories**, **Sources**,
   and **Advanced Tools** and confirm each page loads and its primary action is
   visible.

## Evidence to retain

- command output and timestamps;
- the final batch row and destination volume ID;
- screenshots of connected, active, cancelled, resumed, and completed states;
- Windows CI run URL and uploaded artifact checksum;
- confirmation that no phone/source files were deleted or rewritten.

The deterministic local evidence remains in
`<visual-qa-root>/screenshots` and does not
replace these live checks.

## Safe deterministic UI capture

Do not point the capture harness directly at the protected Round 1 catalog:
SQLite WAL setup needs a writable catalog directory. Copy the database to the
external QA workspace first, then capture from that copy:

```bash
cp /path/to/round1-fresh-workers5.db \
  <visual-qa-root>/latest-source-audit.db
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python scripts/capture_ui_review.py \
  <visual-qa-root>/latest-source-audit.db \
  <visual-qa-root>/latest-offscreen-audit
```

This produces deterministic page screenshots without opening the protected
catalog in write mode.
