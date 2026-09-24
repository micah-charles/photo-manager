# Local macOS Vision POC

This opt-in proof of concept detects face rectangles and full-person rectangles
in explicitly supplied local still images. It calls Apple's Vision framework
through a Swift helper, returns normalized boxes, and does not write to the
photo catalog, change source files, create identities, or contact a service.
No face embeddings or image pixels are returned.

Run from the repository root on macOS with Xcode Command Line Tools installed:

```sh
PYTHONPATH=src python3 -m photovault.cli vision-poc \
  "/path/to/one photo.jpg" "/path/to/another.jpg"
```

The command accepts at most 200 explicit paths. JSON is written to stdout. To
save it, use `--output /path/to/new-result.json`; creation fails if that file
already exists. Each successful image result includes its input path, oriented
pixel dimensions, EXIF orientation, request revisions, elapsed time, face boxes,
and whole-person boxes. A batch continues after a bad image, includes per-image
errors in JSON, and exits with status 1 if any image failed. It exits with status
2 if the helper cannot run. macOS-only Swift and Vision dependencies are not
loaded by the regular app/server.

On macOS 14 and later the POC explicitly requests Vision's CPU compute device
for predictable, opt-in execution; this is not a claim that CPU is faster than
the Neural Engine or GPU. The execution policy must be benchmarked before any
background or bulk-analysis feature is designed.

Boxes use normalized `left/top/right/bottom` coordinates in the EXIF-oriented
image plane, with a top-left origin. The helper converts Vision's normalized
bottom-left rectangles. `template_analysis()` in `photovault.vision_poc` maps
these results to the existing template-engine's optional `analysis.faces` and
`analysis.subjects` shape, without automatically inserting them into the LAN
photo API or persistent database.

This is geometry detection only: it does not say who someone is, cluster the
same person across photos, choose a hero, or judge whether a crop is beautiful.
Treat confidence as the Vision detector's observation score, not identity
confidence. The editor integration, resumable caching, performance benchmark on
a representative private corpus, and UI/privacy controls remain future work.

## Verification

```sh
swiftc src/photovault/platform/macos/local_vision_analyzer.swift -o /tmp/photovault-local-vision
PYTHONPATH=src python3 -m unittest tests.test_vision_poc
```

The Swift compile check verifies framework/API availability on the current Mac;
the Python contract tests cover coordinate validation, template adaptation,
argument-safe invocation, non-macOS refusal, and batch limits. A real image run
must still be reviewed on a user-selected sample before this is integrated into
the app's crop workflow.
