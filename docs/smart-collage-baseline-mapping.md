# Sat 08 Aug 2026 baseline mapping

The supplied reference is a PhotoVault gallery screenshot at
`/Users/charlestan/.codex/attachments/eb1ac43a-bc3c-459c-94de-424134fb221b/image-1.png`.
It contains 28 visible thumbnails under **Sat, 08 Aug 2026**. The PhotoVault
catalog database did not resolve that date, but a direct read-only scan of the
mounted camera exports found the corresponding original files.

The Phase 2 smoke run therefore used 15 explicitly labelled crops derived from
the Sat 08 Aug row, not unrelated images:

| baseline item | original source | status |
|---|---|---|
| `sat-08-00` | `PhotoVault-CameraRound2-SecondPixel/DCIM/Camera/PXL_20260808_152735168.MP.jpg` | visually matched |
| `sat-08-01` | `PhotoVault-CameraRound2-SecondPixel/DCIM/Camera/PXL_20260808_152735971.jpg` | visually matched |
| `sat-08-02` | `PhotoVault-CameraRound2-SecondPixel/DCIM/Camera/PXL_20260808_152736582.jpg` | visually matched |
| `sat-08-03` | `PhotoVault-CameraRound2-SecondPixel/DCIM/Camera/PXL_20260808_152716765.jpg` | visually matched |
| `sat-08-04` … `sat-08-13` | `PhotoVault-CameraRound2-SecondPixel/DCIM/Camera/` (`PXL_20260808_074606533.jpg` through the matched `074203033.MP.jpg` set) | visually matched |
| `sat-08-14` | `PhotoVault-CameraRound1/DCIM/Camera/PXL_20260808_074146892.jpg` | visually matched |

The CLI POC has now been rerun against 15 full-resolution originals at
`/Volumes/ExtremePro/AIWorkspace/smart-collage-poc/sat-08-aug-2026-originals/`.
The catalog still has no asset IDs for these files, so this run is a verified
source-folder experiment rather than a catalog/API acceptance run. The next
integration step is to register these originals in the catalog and expose them
through the existing asset-ID original route.
