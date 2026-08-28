# Open-source landscape

Research checked on 2026-08-21. These projects are references or possible companions, not dependencies of PhotoVault.

| Project | Strong overlap | What PhotoVault should learn | Gap relative to PhotoVault |
| --- | --- | --- | --- |
| [File Hunter](https://github.com/zen-logic/file-hunter) | Offline catalog across USB, backup and network locations; SQLite; duplicate/consolidation workflows | Multi-location/offline catalog UX and audit trail | General file manager; its safety/redundancy policy is not PhotoVault's verified-backup model |
| [Czkawka](https://github.com/qarmin/czkawka) | Cross-platform exact duplicates, similar images/videos, CLI/GUI; MIT core | Its cache + BK-tree approach, configurable hash size/filter and explicit reference paths | Primarily a cleaner; does not model Backup Sets, independently verified copies or offline disk history |
| [PhotoPrism](https://github.com/photoprism/photoprism) | EXIF/indexing, stacks, SHA-1 duplicate handling and perceptual hashes | Separate exact identity, related-file/stack presentation and visual similarity | Primarily a self-hosted photo browser; duplicate deletion/recovery and multi-disk backup integrity are not its core |
| [digiKam](https://www.digikam.org/) | Mature desktop catalog, metadata, face recognition, similarity search and multiple roots | Feature depth and desktop-library workflows | Large C++/Qt application; not a focused independently-verified backup/reconciliation tool |
| [maki](https://github.com/thoherr/maki) | Multi-volume/offline catalog, sidecar metadata and optional local AI | Offline-first catalog and sidecar portability ideas | Different product shape and not a direct replacement for PhotoVault's operation journal |
| [Omoide](https://github.com/EinAeffchen/Omoide) | Offline-capable local-AI photo/video discovery | Privacy-first local AI and cached browsing | Discovery-oriented; its warning about keeping verified backups reinforces PhotoVault's integrity-first scope |

## Design conclusion

PhotoVault should not try to replace all of these projects at once. The strongest combination is:

1. Keep PhotoVault's SHA-256, stable volume identity, Backup Sets, reconciliation, copy verification, quarantine and operation journal as the differentiating core.
2. Keep the current BK-tree/perceptual-hash design, while adopting Czkawka-style tunable hash parameters and cache invalidation as a future refinement.
3. Keep PhotoPrism/digiKam-style metadata, timeline, stacks and people/places as secondary catalog features.
4. Treat File Hunter and maki as the closest UX references for disconnected removable disks.
5. Never infer safe deletion from a visual-similarity group; visual results remain review candidates, while only exact SHA-256 plus an explicit redundancy policy can establish protection.

## Optional semantic backend candidates

The integrity core does not require machine learning. For a later local image
search experiment, the current shortlist is:

- [lakeraai/onnx_clip](https://github.com/lakeraai/onnx_clip) — MIT-licensed,
  ONNX Runtime plus NumPy/PIL, with a ViT-B/32 vision encoder. This is the
  closest fit for PhotoVault's optional `OnnxEmbeddingEngine`.
- [plhery/mobileclip2-onnx](https://huggingface.co/plhery/mobileclip2-onnx) —
  compact MobileCLIP2 ONNX artifacts suitable for exploring lower-resource
  local inference.
- [open_clip](https://github.com/mlfoundations/open_clip) — broad open-source
  model/export reference, but its normal Python workflow is PyTorch-oriented
  and should not be added to the desktop integrity dependency set by default.

These are candidates, not bundled weights or a product recommendation. An
image model must be validated for its input shape, RGB normalization, output
embedding semantics, license and CPU performance before indexing a real
library. Text-only ONNX models such as `all-MiniLM-L6-v2` are not image
encoders and must not be passed to the image indexer.
