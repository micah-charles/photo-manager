# Android source provider

Android MTP is a PhotoVault source provider, not a separate application.
The provider exposes device identity, storage roots, lazy children, metadata,
and eventually bounded object streams. It does not own backup policy,
destinations, catalog state, thumbnails, duplicate logic, or UI.

The current adapter is macOS-only and uses the native IOUSBHost/MTP helper.
It supports one-object bounded streaming to a caller-provided sink for the
Phase B discard test; it does not yet write to a destination.
The Python application reports unavailable on other platforms. A source
fingerprint combines normalized manufacturer/model, USB VID/PID, a protected
serial-derived internal value when available, MTP identity, and storage
observations; complete serial values are never logged or committed.
