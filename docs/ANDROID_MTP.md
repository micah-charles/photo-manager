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

Object handles are session metadata and are never permanent source identity.
The Pixel requires 0xFFFFFFFF for the storage-root GetObjectHandles query but
reports root-child parent 0 in ObjectInfo. DCIM and Camera report MTP
Association format 0x3001.

The native helper includes a bounded GetObject stream mode for the next
hardware test. It emits object bytes directly to a binary sink and retains
the same read-only/source-side safety boundary. No source-side write
operation is allowed.
