"""Build mussa-training-kit.zip: everything the cloud notebook needs, and nothing from the hospital.

The kit holds the training script and verbatim copies of the app's shared modules (ARCADE loader,
preprocessing, metrics, segment names), so training and the app use identical code. ARCADE itself is
downloaded by the notebook from Zenodo; no patient image, store or case database is ever included.

    python tools/training/make_kit.py [--out path/to/mussa-training-kit.zip]
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_AI = ROOT / "src" / "cagsyntax" / "ai"
HERE = Path(__file__).resolve().parent
SHARED = ("arcade.py", "preprocess.py", "metrics.py", "segment_names.py", "sampling.py")

README = """MUSSA training kit (BOTH AI models, ARCADE): the segment model and the stenosis model

Contents: train_segmentation.py (trains either model: --task segments or --task stenosis) and the package
mussa_ai (verbatim copies of the app's shared modules). No patient data, no hospital files.

Use: open MUSSA_train_both_models.ipynb on a free cloud GPU (Google Colab or Kaggle), run all cells,
upload this zip when asked. The notebook trains the segment model, then the stenosis model, and downloads
FOUR files. Copy all four to C:\\Users\\<you>\\MUSSA-data\\models\\ :
    segments.onnx   segments.card.json   stenosis.onnx   stenosis.card.json
Suggest lesions and Run AI on study need all four. See docs/labelling-and-training-guide.md in the project.

Data: ARCADE, https://zenodo.org/records/10390295 (CC0). The notebook downloads it and checks the md5.
Educational and research use; not a certified medical device.
"""


def build_kit(out_zip: Path) -> list[str]:
    """Write the kit and return the names of the files inside it."""
    sys.path.insert(0, str(ROOT / "src"))
    from cagsyntax.ai.segment_names import SEGMENT_NAMES

    out_zip = Path(out_zip)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {
        "train_segmentation.py": (HERE / "train_segmentation.py").read_bytes(),
        "mussa_ai/__init__.py": b"",
        "segment_names.json": json.dumps(list(SEGMENT_NAMES)).encode("utf-8"),
        "README.txt": README.encode("utf-8"),
    }
    for name in SHARED:
        files[f"mussa_ai/{name}"] = (SRC_AI / name).read_bytes()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return list(files)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the MUSSA training kit zip.")
    parser.add_argument("--out", type=Path, default=HERE / "dist" / "mussa-training-kit.zip")
    args = parser.parse_args()
    names = build_kit(args.out)
    print(f"wrote {args.out} ({len(names)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
