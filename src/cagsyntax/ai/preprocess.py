"""The one preprocessing function for the segment model.

Training, evaluation and the app all call this, so they cannot drift apart. It imports only numpy
and Pillow because the training kit receives a verbatim copy of this file (preprocess v1)."""
from __future__ import annotations

import numpy as np
from PIL import Image

INPUT_SIZE = 512


def preprocess(frame: np.ndarray, size: int = INPUT_SIZE) -> np.ndarray:
    """2-D uint8 or uint16 frame of any size -> float32 array of shape (1, size, size) (512 by default).

    Steps: scale to 0..1 by the frame's own minimum and maximum (a constant frame becomes 0.5),
    resize bilinearly to size x size, then standardise with mean 0.5 and std 0.5 (range -1..1)."""
    data = np.asarray(frame)
    if data.ndim != 2:
        raise ValueError(f"Expected a 2-D grayscale frame, got shape {data.shape}.")
    data = data.astype(np.float32)
    low, high = float(data.min()), float(data.max())
    scaled = (data - low) / (high - low) if high > low else np.full_like(data, 0.5)
    resized = Image.fromarray(scaled, mode="F").resize((size, size), Image.Resampling.BILINEAR)
    out = (np.asarray(resized, dtype=np.float32) - 0.5) / 0.5
    return out[None, :, :]


def resize_mask(mask: np.ndarray, height: int, width: int) -> np.ndarray:
    """Boolean mask -> boolean mask of the given size (nearest neighbour)."""
    img = Image.fromarray(np.asarray(mask, dtype=np.uint8) * 255)
    return np.asarray(img.resize((width, height), Image.Resampling.NEAREST)) > 127
