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

The source profile and source item inventory tables preserve normalized source
identity and logical-path observations. MTP object handles are refreshed
transport metadata, not permanent identity.
