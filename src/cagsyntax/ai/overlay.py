from __future__ import annotations

import colorsys

import numpy as np

from .segment_names import SEGMENT_NAMES


def _palette() -> dict[str, tuple[int, int, int]]:
    """25 clearly different colours (golden-ratio hue steps)."""
    colors = {}
    for i, name in enumerate(SEGMENT_NAMES):
        hue = (i * 0.61803398875) % 1.0
        r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 1.0 if i % 2 == 0 else 0.8)
        colors[name] = (int(r * 255), int(g * 255), int(b * 255))
    return colors


SEGMENT_COLORS: dict[str, tuple[int, int, int]] = _palette()


def _check(masks: np.ndarray) -> np.ndarray:
    masks = np.asarray(masks, dtype=bool)
    if masks.ndim != 3 or masks.shape[0] != len(SEGMENT_NAMES):
        raise ValueError(f"Expected masks of shape ({len(SEGMENT_NAMES)}, H, W), got {masks.shape}.")
    return masks


def render_overlay(masks: np.ndarray, alpha: int = 110) -> np.ndarray:
    """Boolean (25, H, W) masks -> uint8 (H, W, 4) RGBA. Transparent where no mask is set; where
    masks overlap, the later segment in table order wins."""
    masks = _check(masks)
    out = np.zeros((masks.shape[1], masks.shape[2], 4), dtype=np.uint8)
    for c, name in enumerate(SEGMENT_NAMES):
        region = masks[c]
        if region.any():
            out[region, :3] = SEGMENT_COLORS[name]
            out[region, 3] = alpha
    return out


def segment_labels(masks: np.ndarray) -> list[tuple[str, float, float]]:
    """(segment name, centroid x, centroid y) for every non-empty mask, in table order."""
    masks = _check(masks)
    labels = []
    for c, name in enumerate(SEGMENT_NAMES):
        ys, xs = np.nonzero(masks[c])
        if len(xs):
            labels.append((name, float(xs.mean()), float(ys.mean())))
    return labels
