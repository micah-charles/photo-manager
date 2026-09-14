# Android MTP transport regression report

Status: reproducible raw-IOUSBHost transport blocker on macOS 26.5.1 with a
Pixel 8 Pro. Read-only metadata traversal passes; sustained object payload
transfer does not.

## Proven boundary

The canonical helper can discover the Pixel, open an MTP session, read device
and storage information, resolve storage root -> DCIM -> Camera, enumerate
6,674 Camera handles, and page ObjectInfo records. The canonical CLI returned
`PAGE 0 50 6674 50`, matching the earlier standalone POC.

The failure begins only when receiving sustained media payload bytes. It is
not explained by stale object handles because `stream-test` resolves a fresh
JPEG handle and streams it in the same native process and MTP session.

## Controlled transport matrix

All rows used the same Pixel, cable, Camera JPEG (7,884,844 bytes), MTP logic,
and a 15-second request timeout. The endpoint is bulk IN `0x81` with a
512-byte maximum packet size.

| MTP receive strategy | USB receive strategy | Result |
| --- | --- | --- |
| `GetObject` | synchronous, 16 KiB, ordinary buffers | FAIL at payload offset 196,596 |
| `GetObject` | synchronous, 16 KiB, reused kernel-backed buffer | FAIL at payload offset 409,588 |
| `GetObject` | synchronous, 512-byte max-packet reads | FAIL at payload offset 108,020 |
| `GetObject` | asynchronous ping-pong, 16 KiB kernel-backed buffers | FAIL at payload offset 196,596 |
| `GetPartialObject`, 64 KiB parts | synchronous, complete MTP transactions | first five parts pass; part 5 at offset 327,680 fails before its first response |

Every failing USB receive reports zero transferred bytes followed by
`IOUSBHostErrorDomain(-536870163)`, `0xe00002ed`
(`kIOReturnNotResponding`). Increasing the control timeout from five to
15 seconds was necessary for reliable Camera handle enumeration but did not
repair payload transfer.

## Conclusions

The evidence rules out these hypotheses:

- stale MTP object handles;
- an invalid `GetObject` container header or initial payload framing;
- only the size of each synchronous read;
- only reuse of kernel-backed memory;
- only synchronous versus asynchronous IOUSBHost scheduling;
- only one long `GetObject` data phase.

`GetPartialObject` is the decisive control. Five independent 64 KiB MTP
transactions complete before the next transaction receives no bytes. The
failure therefore follows cumulative payload traffic on the current raw
IOUSBHost path, not merely a long-lived MTP command.

After the partial-transfer failure, an `ioreg -p IOUSBHost` search returned
only the registry root diagnostics and no Pixel/Google device entry. The
apparent `Pixel` match came from an unrelated `PixelAveraging...` class name
inside that diagnostics dictionary. This is consistent with the USB device
or transport entering a bad state after the timeout; it is not proof that the
phone remained available.

## Stop rule and next control

Do not continue tuning chunk sizes, timeouts, retries, endpoint clearing, or
sync/async variants on this helper without new evidence. These dimensions
have now been isolated and do not explain the fault. A failed attempt can
remove the Pixel from IOUSBHost and force a physical reconnect, so repeated
raw-helper tests impose real user cost.

The next diagnostic is one bounded mature-client control on the same Mac,
Pixel, cable, and a comparable JPEG after one clean reconnect. Copy one file
from the phone to a temporary Mac destination and perform no phone-side
writes or deletes.

- If the mature client succeeds, treat this raw IOUSBHost transport as the
  defective/incompatible boundary and make an explicit transport architecture
  decision before Level 6 continues.
- If it fails similarly, investigate the shared macOS 26 / Pixel / cable or
  device-state boundary before changing PhotoVault code.

The diagnostic implementation remains in the repository because it captures
the reproducible evidence. It is not considered a production-ready object
transport.
