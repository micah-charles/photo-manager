# Android source integration audit

Date: 2026-08-28

## Existing reusable components

- photovault.backup.copy: reviewed copy plans, source revalidation, SHA-256
  destination verification, conflict protection, and operation history.
- photovault.catalog.scanner: catalog registration, media classification,
  metadata, thumbnails, and incremental filesystem scanning.
- photovault.catalog.hashing: authoritative SHA-256 implementation.
- photovault.platform.base and platform.provider: provider boundary and stable
  volume identity model.
- photovault.observability: structured operational events.
- CLI dispatch and PySide6 worker patterns: shared entry points without
  duplicating business logic.

## Required new components

- A capability-based PhotoSource contract for non-filesystem sources, with
  streaming represented as an optional readable capability.
- Android source identity and normalized object metadata types.
- A macOS-only native IOUSBHost/MTP helper reached through a narrow JSON
  control protocol for discovery and metadata.
- A bounded binary stream operation for future object import.
- CLI discovery/list diagnostics before GUI integration.
- Hardware-independent fake source/bridge tests.

## Components that must not be duplicated

Android must not introduce a second catalog, copy engine, SHA-256
implementation, duplicate detector, thumbnail pipeline, backup history model,
or destructive sync workflow. Android is a source provider consumed by the
existing application services.

## Integration boundary

Python owns source selection, copy/import plans, destinations, hashing,
catalog/history, thumbnails, duplicates, and UI. The native helper owns only
IOUSBHost transport, MTP session/metadata/object enumeration, and bounded
object reads. Raw MTP packets must not cross into normal Python business logic.

## Native/build implications

The proven native code is Objective-C using public IOUSBHost APIs and must be
built as a macOS arm64 helper. It is intentionally not rewritten in Python.
The helper runs as an unsandboxed normal-user process during this integration;
signing, notarization, App Sandbox, entitlements, and distribution remain
release risks.

## Packaging implications

Development builds can locate a repository helper. A production bundle must
include the helper, verify its architecture, and document the unsandboxed
native-access requirement. Windows remains feature-detected and unsupported
for this adapter.
