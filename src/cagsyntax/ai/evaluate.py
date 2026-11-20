from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .arcade import ArcadeSplit
from .segment_names import SEGMENT_NAMES


@dataclass
class EvalReport:
    split: str
    images: int
    per_segment: dict[str, dict]      # dice, iou, truth_pixels, pred_pixels per segment name
    macro_dice: float
    macro_iou: float
    segments_evaluated: int           # segments that occur in the truth or the prediction


def evaluate_model(segmenter, split: ArcadeSplit, limit: int | None = None,
                   progress: Callable[[int, int], None] | None = None) -> EvalReport:
    """Run a model over an ARCADE split. Dice and IoU per segment come from pixel counts pooled over
    all images (so a large segment in one image weighs more than a tiny one in another); the macro
    averages cover only segments that occur in the truth or the prediction."""
    n = min(len(split), limit) if limit else len(split)
    count = len(SEGMENT_NAMES)
    inter, pred_px, truth_px = (np.zeros(count, dtype=np.int64) for _ in range(3))
    for i in range(n):
        truth = split.load_masks(i)
        pred = np.asarray(segmenter.predict(split.load_image(i)), dtype=bool)
        if pred.shape != truth.shape:
            raise ValueError(f"The model's prediction has shape {pred.shape}; expected {truth.shape}.")
        inter += (pred & truth).sum(axis=(1, 2))
        pred_px += pred.sum(axis=(1, 2))
        truth_px += truth.sum(axis=(1, 2))
        if progress is not None:
            progress(i + 1, n)
    per_segment: dict[str, dict] = {}
    for c, name in enumerate(SEGMENT_NAMES):
        total, union = int(pred_px[c] + truth_px[c]), int(pred_px[c] + truth_px[c] - inter[c])
        per_segment[name] = {
            "dice": 2.0 * int(inter[c]) / total if total else None,
            "iou": int(inter[c]) / union if union else None,
            "truth_pixels": int(truth_px[c]), "pred_pixels": int(pred_px[c]),
        }
    dices = [v["dice"] for v in per_segment.values() if v["dice"] is not None]
    ious = [v["iou"] for v in per_segment.values() if v["iou"] is not None]
    return EvalReport(split=split.root.name, images=n, per_segment=per_segment,
                      macro_dice=sum(dices) / len(dices) if dices else 0.0,
                      macro_iou=sum(ious) / len(ious) if ious else 0.0, segments_evaluated=len(dices))


def report_to_json(report: EvalReport) -> dict:
    return {"split": report.split, "images": report.images, "macro_dice": report.macro_dice,
            "macro_iou": report.macro_iou, "segments_evaluated": report.segments_evaluated,
            "per_segment": report.per_segment}


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def report_to_markdown(report: EvalReport) -> str:
    lines = [
        "# Segment model evaluation", "",
        f"Split: {report.split} ({report.images} images)",
        f"Macro Dice: {report.macro_dice:.3f}   macro IoU: {report.macro_iou:.3f}   "
        f"segments evaluated: {report.segments_evaluated}", "",
        "Dice and IoU are computed from pixel counts pooled over all images. "
        "A dash means the segment is neither in the ground truth nor predicted.", "",
        "| Segment | Dice | IoU | truth px | predicted px |", "|---|---|---|---|---|",
    ]
    for name in SEGMENT_NAMES:
        v = report.per_segment[name]
        lines.append(f"| {name} | {_fmt(v['dice'])} | {_fmt(v['iou'])} | {v['truth_pixels']} | {v['pred_pixels']} |")
    return "\n".join(lines) + "\n"
