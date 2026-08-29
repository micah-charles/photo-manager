# Android MTP source

The proven Pixel 8 Pro path is:

IOUSBHost interface 0 -> MTP OpenSession -> device/storage metadata ->
object handles and object metadata.

The interface is class 0x06, subclass 0x01, protocol 0x01, with bulk OUT
0x01, bulk IN 0x81, and interrupt IN 0x82.

Phase 0C passed OpenSession, GetDeviceInfo, GetStorageIDs, GetStorageInfo,
and CloseSession. Phase 1A passed lazy traversal of storage 65537 root ->
DCIM -> Camera, locating 6,674 Camera objects and sampling 50 metadata
records in about 6.07 seconds.

The canonical Photo Manager CLI now reproduces that traversal against the
same Pixel: root -> DCIM -> Camera returned a paged result of 50 from 6,674
objects. Path components are resolved lazily and storage metadata is cached
from the identity session so normal traversal retains the proven MTP
transaction sequence. Camera listing is paged and does not fetch metadata for
all objects automatically.

Object handles are session metadata and are never permanent source identity.
The Pixel requires 0xFFFFFFFF for the storage-root GetObjectHandles query but
reports root-child parent 0 in ObjectInfo. DCIM and Camera report MTP
Association format 0x3001.

The native helper includes bounded full-object and partial-object diagnostic
stream modes. They emit object bytes directly to a binary sink and retain the
same read-only/source-side safety boundary. No source-side write operation is
allowed.

Level 6 is currently blocked by the raw IOUSBHost payload transport. Valid
`GetObject` data begins, but the bulk-IN path stops responding after a few
hundred KiB. Synchronous 16 KiB, synchronous 512-byte max-packet, asynchronous
ping-pong, reused kernel buffers, and independent 64 KiB `GetPartialObject`
transactions all reproduce the boundary. See
`ANDROID_MTP_TRANSPORT_REGRESSION_REPORT.md` for the evidence matrix and stop
rule.
