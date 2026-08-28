# Android native bridge

PhotoVault uses a narrow helper boundary for the macOS Android source.

## Control protocol

The first integration uses newline-delimited JSON requests and responses on
stdin/stdout. Each response is one normalized result or one structured error.
The protocol exposes source-level concepts only:

- list_devices
- open_device
- device_info
- list_storages
- list_children
- object_info
- close_device

Raw MTP containers, endpoint addresses, and transaction IDs remain inside the
native helper.

## Data protocol

Media bytes must not be encoded as JSON. The future open_object_stream
operation will use a separate bounded binary stream. The first milestone only
exercises discovery and metadata.

## Availability

AndroidMacMtpSource is available only on macOS when the helper is present.
On other platforms it returns an explicit unavailable result rather than
crashing. No root, sudo, DeviceCapture, libusb, libmtp, kext, SIP change, or
privileged daemon is part of this design.
