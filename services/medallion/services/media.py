"""Media derivation — decode a blob-v2 image into lightweight, inline artifacts.

The heavy original image stays a referenced blob in bronze; a downstream (silver) stage derives small
artifacts from it that are cheap to store *inline*: a thumbnail (downscaled PNG) and a fixed-size embedding
(deterministic pixel features — no ML model). This is the realistic per-stage transform the generic cascade
mover leaves to a distributed job (see ``compute.py``); here it runs in-process so the medallion demo shows
a real multimodal pipeline end to end.
"""

from __future__ import annotations

import io

from PIL import Image

THUMBNAIL_SIZE = (128, 128)
EMBEDDING_DIMS = 8


def derive_thumbnail(image_bytes: bytes, size: tuple[int, int] = THUMBNAIL_SIZE) -> bytes:
    """A downscaled PNG thumbnail of ``image_bytes`` — small enough to store INLINE (not a blob)."""
    with Image.open(io.BytesIO(image_bytes)) as image:
        thumbnail = image.convert("RGB")
        thumbnail.thumbnail(size)
        buffer = io.BytesIO()
        thumbnail.save(buffer, format="PNG")
        return buffer.getvalue()


def derive_embedding(image_bytes: bytes, dims: int = EMBEDDING_DIMS) -> list[float]:
    """A deterministic ``dims``-length feature vector — the luminance of the image downsampled to ``dims``
    columns. Real pixel-derived features (not a random vector), so silver's embedding actually depends on
    the media, without pulling in an ML-model dependency.
    """
    with Image.open(io.BytesIO(image_bytes)) as image:
        columns = image.convert("L").resize((dims, 1), resample=Image.Resampling.BILINEAR)
        # An 8-bit "L" image's tobytes() is one byte per pixel, so iterating yields ints (0-255); the
        # explicit resample pins the downsample so the embedding is deterministic across environments.
        return [value / 255.0 for value in columns.tobytes()]
