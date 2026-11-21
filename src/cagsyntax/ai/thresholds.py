"""Tune the per-segment probability cut-offs of a segment model on a split (use validation, not test).

A model trained on rare segments is often under-confident about them, so a fixed 0.5 cut-off predicts
nothing for those segments. This picks, for each segment, the cut-off with the best Dice on the split."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .arcade import ArcadeSplit
from .segment_names import SEGMENT_NAMES
from .segmenter import ModelUnavailable

DEFAULT_GRID = (0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9)
DEFAULT_THRESHOLD = 0.5


@dataclass
class ThresholdResult:
    thresholds: dict            # segment name -> chosen cut-off
    images: int
    before_macro_dice: float    # every segment at 0.5
    after_macro_dice: float     # each segment at its chosen cut-off
    per_segment: dict           # name -> {"before": dice or None, "after": dice or None}
    split: str


def tune_thresholds(segmenter, split: ArcadeSplit, limit: int | None = None,
                    progress: Callable[[int, int], None] | None = None, grid=DEFAULT_GRID) -> ThresholdResult:
    """Run the model once per image and count, for every segment and every cut-off in `grid`, the overlap
    and sizes of prediction and truth (pooled over all images). Needs only counts, so memory stays small."""
    grid = np.asarray(sorted(set(grid) | {DEFAULT_THRESHOLD}), dtype=np.float32)
    count, steps = len(SEGMENT_NAMES), len(grid)
    inter, pred_px = np.zeros((count, steps), dtype=np.int64), np.zeros((count, steps), dtype=np.int64)
    truth_px = np.zeros(count, dtype=np.int64)
    n = min(len(split), limit) if limit else len(split)
    for i in range(n):
        truth = split.load_masks(i)
        prob = np.asarray(segmenter.probabilities(split.load_image(i)), dtype=np.float32)
        if prob.shape != truth.shape:
            raise ValueError(f"The model's probabilities have shape {prob.shape}; expected {truth.shape}.")
        truth_px += truth.sum(axis=(1, 2))
        for c in range(count):
            for k, t in enumerate(grid):
                guess = prob[c] > t
                pred_px[c, k] += int(guess.sum())
                inter[c, k] += int((guess & truth[c]).sum())
        if progress is not None:
            progress(i + 1, n)
    default_k = int(np.flatnonzero(grid == DEFAULT_THRESHOLD)[0])
    thresholds, per_segment, before, after = {}, {}, [], []
    for c, name in enumerate(SEGMENT_NAMES):
        total = pred_px[c] + truth_px[c]                       # per cut-off
        dice = np.where(total > 0, 2.0 * inter[c] / np.maximum(total, 1), np.nan)
        base = None if total[default_k] == 0 else float(dice[default_k])
        if truth_px[c] == 0 or np.all(np.isnan(dice)):
            thresholds[name], best = DEFAULT_THRESHOLD, base      # never present: nothing to tune on
        else:
            top = np.nanmax(dice)
            tied = np.flatnonzero(np.isclose(dice, top, atol=1e-9))
            k = int(tied[np.argmin(np.abs(grid[tied] - DEFAULT_THRESHOLD))])      # ties go closest to 0.5
            thresholds[name], best = round(float(grid[k]), 4), float(dice[k])
        per_segment[name] = {"before": base, "after": best}
        if base is not None:
            before.append(base)
        if best is not None:
            after.append(best)
    return ThresholdResult(thresholds=thresholds, images=n,
                           before_macro_dice=sum(before) / len(before) if before else 0.0,
                           after_macro_dice=sum(after) / len(after) if after else 0.0,
                           per_segment=per_segment, split=split.root.name)


def write_thresholds(model_path: Path, result: ThresholdResult) -> Path:
    """Store the cut-offs in the model card next to the model; every other card field is kept."""
    card_path = Path(model_path).with_name(Path(model_path).stem + ".card.json")
    try:
        card = json.loads(card_path.read_text(encoding="utf-8"))
        if not isinstance(card, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        raise ModelUnavailable(f"The model card {card_path.name} is missing or unreadable ({exc}); "
                               "nothing was written.") from exc
    card["thresholds"] = dict(result.thresholds)
    card["thresholds_tuned_on"] = f"{result.split} ({result.images} images)"
    card_path.write_text(json.dumps(card, indent=1), encoding="utf-8")
    return card_path
