"""Measure a segment model on an ARCADE split.

    python tools/ai/evaluate_segmentation.py --model C:\\...\\MUSSA-data\\models\\segments.onnx
        --split arcade/arcade/syntax/test [--limit 50] [--out segment_eval]

Prints the table and writes report.json and report.md. Runs on the CPU; the 300 test images take a
few minutes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cagsyntax.ai.arcade import ArcadeSplit  # noqa: E402
from cagsyntax.ai.evaluate import evaluate_model, report_to_json, report_to_markdown  # noqa: E402
from cagsyntax.ai.segmenter import ModelUnavailable, Segmenter  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the MUSSA segment model on an ARCADE split.")
    parser.add_argument("--model", type=Path, required=True, help="segments.onnx (with segments.card.json beside it)")
    parser.add_argument("--split", type=Path, required=True, help="an ARCADE split folder, e.g. arcade/arcade/syntax/test")
    parser.add_argument("--limit", type=int, default=None, help="evaluate only the first N images")
    parser.add_argument("--out", type=Path, default=Path("segment_eval"), help="folder for report.json and report.md")
    args = parser.parse_args()
    try:
        segmenter = Segmenter.load(args.model)
    except ModelUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    def progress(done: int, total: int) -> None:
        if done == total or done % 20 == 0:
            print(f"  {done}/{total} images", file=sys.stderr, flush=True)

    report = evaluate_model(segmenter, ArcadeSplit(args.split), args.limit, progress)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report_to_json(report), indent=1), encoding="utf-8")
    markdown = report_to_markdown(report)
    (args.out / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"Macro Dice {report.macro_dice:.3f} on {report.images} images; report written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
