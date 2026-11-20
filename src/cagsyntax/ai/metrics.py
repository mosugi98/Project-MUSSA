from __future__ import annotations

import numpy as np

from .segment_names import SEGMENT_NAMES


def _check(pred: np.ndarray, truth: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pred, truth = np.asarray(pred, dtype=bool), np.asarray(truth, dtype=bool)
    if pred.shape != truth.shape:
        raise ValueError(f"Shape mismatch: {pred.shape} vs {truth.shape}.")
    return pred, truth


def dice(pred: np.ndarray, truth: np.ndarray) -> float | None:
    """Dice overlap of two boolean masks. None when both are empty (segment absent and not predicted)."""
    pred, truth = _check(pred, truth)
    total = int(pred.sum()) + int(truth.sum())
    if total == 0:
        return None
    return 2.0 * int((pred & truth).sum()) / total


def iou(pred: np.ndarray, truth: np.ndarray) -> float | None:
    """Intersection over union. None when both are empty."""
    pred, truth = _check(pred, truth)
    union = int((pred | truth).sum())
    if union == 0:
        return None
    return int((pred & truth).sum()) / union


def per_segment_scores(preds: np.ndarray, truths: np.ndarray) -> dict[str, dict]:
    """Scores for arrays of shape (25, H, W): per segment name, dice, iou and the pixel counts."""
    preds, truths = _check(preds, truths)
    if preds.ndim != 3 or preds.shape[0] != len(SEGMENT_NAMES):
        raise ValueError(f"Expected shape ({len(SEGMENT_NAMES)}, H, W), got {preds.shape}.")
    return {name: {"dice": dice(preds[i], truths[i]), "iou": iou(preds[i], truths[i]),
                   "truth_pixels": int(truths[i].sum()), "pred_pixels": int(preds[i].sum())}
            for i, name in enumerate(SEGMENT_NAMES)}
