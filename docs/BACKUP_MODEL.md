# PhotoVault Backup Model

PhotoVault treats a backup as a verified copy of an exact-content `Asset` on a
different catalogued volume. Filenames and paths help humans reconcile files,
but never establish backup integrity.

## Core objects

- `Asset`: one exact SHA-256 content identity.
- `AssetLocation`: one occurrence of an asset on a volume and relative path.
- `BackupSet`: one `PRIMARY`, one or more `BACKUP` members, a scope and a
  minimum required copy count.
- `verification_history`: the immutable-ish record of destination hash checks
  performed by copy operations.

The SQLite catalog is local metadata. Originals remain ordinary files on their
volumes and are never placed inside a proprietary container.

## Protection states

The redundancy audit reports:

- `VERIFIED_REDUNDANT`: the required number of connected member volumes contain
  the same SHA-256 asset.
- `MISSING_BACKUP`: a primary asset has fewer than the configured required
  copies.
- `BACKUP_ONLY`: an asset exists on a backup member but has no active primary
  location. It is never deleted automatically.
- `CONFLICT`: the same relative path has different SHA-256 content.
- `UNPROTECTED`: no backup member provides the required protection.
- `MULTI_COPY`: at least three connected physical member volumes contain the
  exact asset.
- `OFFLINE_UNKNOWN`: a required member volume is offline, so the current copy
  count cannot be fully revalidated.

`MULTI_COPY` and `VERIFIED_REDUNDANT` count as protected. A copy is counted
only after its destination has been hashed and recorded as verified.

## Reconciliation and copy policy

Reconciliation first compares relative paths, then matches unmatched files by
SHA-256 so renames and moves are visible as verified matches. It reports
`MAIN_ONLY`, `BACKUP_ONLY`, `VERIFIED`, `CONFLICT` and `UNKNOWN_OFFLINE`.

`copy-plan` is a dry-run operation journal. `execute-copy` re-hashes each source
before copying, refuses to overwrite a different existing destination, hashes
the destination after copying, and adds the destination location only after a
successful verification. Partial failures remain visible in the journal.

The model deliberately does not infer physical independence from filenames.
Volume identity and user-assigned Backup Set membership are required; users
should place copies on genuinely separate devices for meaningful redundancy.

