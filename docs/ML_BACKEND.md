# Optional ML Backend

PhotoVault's integrity and catalog features do not require machine learning.
The optional `ml` extra adds Pillow, NumPy and ONNX Runtime; it does not
download model weights.

## Image model contract

`OnnxEmbeddingEngine` accepts a user-supplied ONNX model with:

- one rank-4 NCHW image input;
- three RGB channels;
- a static image size matching `--image-size`, or dynamic spatial dimensions;
- at least one output tensor that can be flattened to a finite vector.

PhotoVault applies RGB conversion, resize, float normalization and persists
the resulting vector under the selected model name. The source SHA-256 is
stored with the vector, so unchanged assets skip inference and changed assets
are recomputed.

Example:

```bash
python -m pip install -e '.[ml]'
PYTHONPATH=src python -m photovault.cli \
  --catalog ~/.photovault/catalog.db \
  embedding-index --model /path/to/image_encoder.onnx --model-name mobileclip
```

The preprocessing mean/std must match the exported model. CLIP-family models
are not interchangeable solely because they are both ONNX; validate input
shape, normalization, output semantics, license and CPU performance first.
Text-only encoders such as `all-MiniLM-L6-v2` are rejected by the image
backend because their input is not rank-4 NCHW.

The current local smoke test used a temporary three-channel ONNX image model
and verified inference, persistence, SHA-256 cache skipping and cosine search.
It is a plumbing test, not a quality benchmark for a production CLIP model.

