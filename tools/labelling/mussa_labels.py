"""Labelling helpers for MUSSA, in three steps.

    python tools/labelling/mussa_labels.py frames --store "C:\\Users\\<you>\\MUSSA-data\\store" --out labelling\\png
    python tools/labelling/mussa_labels.py check  --folder labelling\\cvat-export
    python tools/labelling/mussa_labels.py split  --source labelling\\cvat-export --out labelling\\labelled

frames: one PNG per series (the middle frame; --frame N or --frame all) to load into the labelling tool.
check:  explains every problem in a labelled folder in plain words; exits 1 if there is any.
split:  makes train and val folders for training, keeping every study whole.
See docs/labelling-and-training-guide.md."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cagsyntax.ai.labels import check_coco, export_frames, format_check, split_coco  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Labelling helpers for MUSSA.")
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("frames", help="export one PNG per series for labelling")
    f.add_argument("--store", type=Path, required=True, help="the MUSSA store folder (MUSSA-data\\store)")
    f.add_argument("--out", type=Path, required=True, help="a new, empty folder for the PNG files")
    f.add_argument("--frame", default="middle", help="middle (default), all, or a frame number")
    c = sub.add_parser("check", help="check a labelled folder")
    c.add_argument("--folder", type=Path, required=True, help="folder with images/ and annotations/")
    s = sub.add_parser("split", help="split a labelled folder into train and val")
    s.add_argument("--source", type=Path, required=True, help="the labelling tool's COCO export folder")
    s.add_argument("--out", type=Path, required=True, help="a new, empty folder for train/ and val/")
    s.add_argument("--val-fraction", type=float, default=0.2)
    args = parser.parse_args(argv)
    try:
        if args.command == "frames":
            frame = args.frame if args.frame in ("middle", "all") else int(args.frame)
            result = export_frames(args.store, args.out, frame)
            print(f"Wrote {len(result.written)} image(s) to {args.out} (frames.csv lists where each came from).")
            for name, reason in result.skipped:
                print(f"  skipped {name}: {reason}")
            return 0 if result.written else 1
        if args.command == "check":
            report = check_coco(args.folder)
            print(format_check(report))
            return 0 if report.ok else 1
        result = split_coco(args.source, args.out, args.val_fraction)
        print(f"train: {result.train_images} images, {result.train_annotations} labels\n"
              f"val:   {result.val_images} images, {result.val_annotations} labels\n"
              f"(from {result.groups} studies; each study is in one split only)\nWritten to {args.out}")
        return 0
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
