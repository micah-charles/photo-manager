# PhotoVault Safety Model

PhotoVault is integrity-first and conservative by default.

## Non-negotiable rules

1. Never silently delete an original.
2. Never overwrite a conflicting destination automatically.
3. Never mark a copy verified from filename, path or size alone.
4. Use SHA-256 content verification for exact identity and copy completion.
5. Journal every filesystem-changing operation.
6. Provide a dry-run plan before copy or quarantine execution.
7. Treat removable volumes as intermittently offline.
8. Prefer reversible quarantine over permanent deletion.
9. Keep the catalog and originals separate; the catalog is not required to
   recover the media files.

## Filesystem-changing operations

Copy execution records an operation, revalidates the source, refuses a
different destination, verifies the copied destination and records the result
in `verification_history`.

Quarantine moves files into a per-operation `.PhotoVaultQuarantine/` directory,
creates a JSON manifest containing paths, asset IDs, expected hashes and the
reason, and verifies the moved file. `undo-quarantine` re-hashes the quarantined
file, refuses an occupied or conflicting original path, restores it, verifies
the restored content and updates the catalog only after success. Permanent
deletion is not implemented by the normal workflow.

## Failure handling

Scans use a `scan_sessions` row and per-path `scan_errors`; a failed session is
marked `FAILED` and does not erase the previous catalog view. GUI scans and
confirmed operations run away from the UI thread with independent SQLite
connections. Interrupted or partial operations remain in the operation journal
with per-item results.

The `photovault` logger also emits compact JSON events for scan and modifying
operation start/completion/failure, including session/operation ID, volume or
asset counts, error counts and duration. Applications may configure handlers
for these events; normal CLI output is unchanged.

## User review boundaries

Visual duplicate groups, GPS clusters, semantic results and `BACKUP_ONLY`
items are advisory. They do not authorize deletion or overwriting. Any future
destructive feature must be a separate explicit action with a preview,
confirmation, journal entry and recoverability analysis.
