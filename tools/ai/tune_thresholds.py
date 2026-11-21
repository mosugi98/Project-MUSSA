"""Tune the per-segment cut-offs of a segment model on the ARCADE validation split.

    python tools/ai/tune_thresholds.py --model C:\\...\\models\\segments.onnx --split arcade/arcade/syntax/val
        [--limit 50] [--write]

Without --write nothing is changed: the table is only printed. With --write the cut-offs are stored in the
model card (segments.card.json) next to the model; every other card field is kept. Tune on the validation
split and judge the result on the test split with evaluate_segmentation.py, never the other way round.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cagsyntax.ai.arcade import ArcadeSplit  # noqa: E402
from cagsyntax.ai.segmenter import ModelUnavailable, Segmenter  # noqa: E402
from cagsyntax.ai.thresholds import tune_thresholds, write_thresholds  # noqa: E402


def fmt(value) -> str:
    return "-" if value is None else f"{value:.3f}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Tune per-segment cut-offs of the MUSSA segment model.")
    parser.add_argument("--model", type=Path, required=True, help="segments.onnx (with segments.card.json beside it)")
    parser.add_argument("--split", type=Path, required=True, help="the ARCADE validation folder, e.g. arcade/arcade/syntax/val")
    parser.add_argument("--limit", type=int, default=None, help="use only the first N images")
    parser.add_argument("--write", action="store_true", help="store the cut-offs in the model card")
    args = parser.parse_args()
    if args.split.name.lower() == "test":
        print("error: tune on the validation split, not the test split, or the test result stops being honest.",
              file=sys.stderr)
        return 2
    try:
        segmenter = Segmenter.load(args.model)
    except ModelUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    def progress(done: int, total: int) -> None:
        if done == total or done % 20 == 0:
            print(f"  {done}/{total} images", file=sys.stderr, flush=True)

    result = tune_thresholds(segmenter, ArcadeSplit(args.split), args.limit, progress)
    print(f"{'Segment':<8}{'cut-off':>8}{'Dice @0.5':>11}{'Dice tuned':>12}")
    for name, cut in result.thresholds.items():
        row = result.per_segment[name]
        print(f"{name:<8}{cut:>8.2f}{fmt(row['before']):>11}{fmt(row['after']):>12}")
    print(f"Macro Dice on {result.images} {result.split} images: {result.before_macro_dice:.3f} -> "
          f"{result.after_macro_dice:.3f}")
    if args.write:
        print(f"Cut-offs written to {write_thresholds(args.model, result)}")
    else:
        print("Nothing was written (add --write to store the cut-offs in the model card).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
