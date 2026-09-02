# PhotoVault Phase 0 live acceptance runbook

This runbook covers the two checks that cannot be proven by the local Qt test
suite: a real Android Companion transfer and a real Windows package smoke test.
It is intentionally read-only on the phone. Put the catalog, logs, and copied
media on the external `/Volumes/ExtremePro` drive.

## Pixel Companion transfer

1. On the Pixel, open PhotoVault Companion, choose a sharing duration, and keep
   the sharing notification active. Keep the Mac and phone on the same Wi-Fi.
2. Start PhotoVault with an external catalog:

   ```bash
   cd /Volumes/ExtremePro/project/codex/photo-manager-github
   PYTHONPATH=src .venv/bin/python -m photovault.ui \
     --catalog /Volumes/ExtremePro/PhotoVault-CameraRound1-Fresh/live-acceptance.db
   ```

3. Open **Android Devices**, enter the current Companion URL/token, and press
   **Connect**. Confirm the device identity and folder inventory.
4. Select `DCIM/Camera`, first choose a small test limit, and choose a
   destination under `/Volumes/ExtremePro`. Verify the plan before starting.
5. Start the transfer and record the live file count, bytes, elapsed time,
   average speed, interval speed, and ETA. Cancel once during the small test;
   confirm the UI says it is safe to resume.
6. Start the same profile again. Confirm already-imported files are skipped,
   partial files resume safely, and the final result is shown in **Operations**.
7. Verify the catalog batch history from Terminal:

   ```bash
   PYTHONPATH=src .venv/bin/python -m photovault.cli \
     --catalog /Volumes/ExtremePro/PhotoVault-CameraRound1-Fresh/live-acceptance.db \
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

## Evidence to retain

- command output and timestamps;
- the final batch row and destination volume ID;
- screenshots of connected, active, cancelled, resumed, and completed states;
- Windows CI run URL and uploaded artifact checksum;
- confirmation that no phone/source files were deleted or rewritten.

The deterministic local evidence remains in
`/Volumes/ExtremePro/AIWorkspace/PhotoVault-VisualQA/screenshots` and does not
replace these live checks.

## Safe deterministic UI capture

Do not point the capture harness directly at the protected Round 1 catalog:
SQLite WAL setup needs a writable catalog directory. Copy the database to the
external QA workspace first, then capture from that copy:

```bash
cp /Volumes/ExtremePro/PhotoVault-CameraRound1-Fresh/round1-fresh-workers5.db \
  /Volumes/ExtremePro/AIWorkspace/PhotoVault-VisualQA/latest-source-audit.db
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python scripts/capture_ui_review.py \
  /Volumes/ExtremePro/AIWorkspace/PhotoVault-VisualQA/latest-source-audit.db \
  /Volumes/ExtremePro/AIWorkspace/PhotoVault-VisualQA/latest-offscreen-audit
```

This produces deterministic page screenshots without opening the protected
catalog in write mode.
