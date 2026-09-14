# Android import model

Android remains a source, while PhotoVault's existing copy/import services
remain responsible for destination policy, SHA-256, operation history,
conflicts, and catalog integrity.

The first safe import path is:

AndroidMtpPhotoSource -> bounded stream -> partial destination ->
SHA-256 and size verification -> atomic final rename -> existing catalog and
operation journal.

The source is never deleted or modified. No destructive move, two-way sync,
deletion propagation, filename-only duplicate decision, or destination
overwrite is allowed.

The controlled CLI entry point is `android import-one`; it requires an explicit
object ID, destination root, and registered destination volume. For a reviewed
folder, `android import-folder <logical-path> <destination-root>` enumerates
media, prints `NEW`/`ALREADY_IMPORTED`/`CONFLICT` decisions, and imports only
new items. The batch path is still copy-only: there is no source deletion or
destructive sync command.

The source profile and source item inventory tables preserve normalized source
identity and logical-path observations. Completed transfers are recorded in
`source_imports` with source metadata, destination identity/path, SHA-256 and
operation ID. MTP object handles are refreshed transport metadata, not
permanent identity.
