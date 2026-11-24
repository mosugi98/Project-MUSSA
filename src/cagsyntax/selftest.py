"""Check that this install of MUSSA can do its job. Run it on a new PC, or after packaging:

    python -m cagsyntax.selftest          (or  MUSSA.exe --selftest)

It touches no patient data and opens no window. Each check reports OK or FAILED with the reason."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _check_qt() -> str:
    from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
    return f"PySide6 {QtCore.__version__}"


def _decoder(uid_name: str) -> str:
    from pydicom import uid
    from pydicom.pixels import get_decoder
    decoder = get_decoder(getattr(uid, uid_name))
    if not decoder.is_available:
        raise RuntimeError("no decoder plugin is available (pylibjpeg-libjpeg missing from the install)")
    return "available"


def _check_jpeg_lossless() -> str:
    return _decoder("JPEGLosslessSV1")


def _check_jpeg_baseline() -> str:
    return _decoder("JPEGBaseline8Bit")


def _check_onnxruntime() -> str:
    import onnxruntime
    providers = onnxruntime.get_available_providers()
    if "CPUExecutionProvider" not in providers:
        raise RuntimeError(f"no CPU provider (found {providers})")
    return f"onnxruntime {onnxruntime.__version__}"


def _check_pillow() -> str:
    import numpy as np
    from PIL import Image
    image = Image.fromarray(np.zeros((4, 4), dtype=np.uint8)).resize((8, 8))
    return f"Pillow {Image.__version__}, resize to {image.size}"


def _check_sqlite() -> str:
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.execute("create table t (x integer)")
    con.execute("insert into t values (1)")
    value = con.execute("select x from t").fetchone()[0]
    con.close()
    if value != 1:
        raise RuntimeError("the database returned the wrong value")
    return f"SQLite {sqlite3.sqlite_version}"


def _check_scoring_engine() -> str:
    from .scoring import Case, Lesion, score_case
    lesion = Lesion(segments=["8"], occlusion=False, trifurcation=0, bifurcation="none", severe_tortuosity=False,
                    length_gt20=False, heavy_calcification=False, thrombus=False)
    result = score_case(Case(dominance="right", scoring_dominance=None, lesions=[lesion]))
    if result.status != "complete" or result.total != 2.0:
        raise RuntimeError(f"expected 2.0 for one mid-LAD stenosis, got {result.status} {result.total}")
    return "a single mid-LAD stenosis scores 2.0"


def _check_artery_map_image() -> str:
    from PIL import Image
    from .ui.artery_map import IMAGE_PATH
    with Image.open(IMAGE_PATH) as im:
        im.load()
        return f"heart illustration {im.width}x{im.height}"


CHECKS = (
    ("Qt (PySide6)", lambda: _check_qt()),
    ("DICOM JPEG Lossless decoder", lambda: _check_jpeg_lossless()),
    ("DICOM JPEG Baseline decoder", lambda: _check_jpeg_baseline()),
    ("ONNX Runtime (CPU)", lambda: _check_onnxruntime()),
    ("Image library (Pillow)", lambda: _check_pillow()),
    ("SQLite", lambda: _check_sqlite()),
    ("Scoring engine", lambda: _check_scoring_engine()),
    ("Diagram image (artery map)", lambda: _check_artery_map_image()),
)


AI_CHECK_NAME = "AI segment model (optional)"


def default_data_dir() -> Path:
    return Path.home() / "MUSSA-data"


def check_ai_model(data_dir: Path) -> Check:
    """The segment model is optional: none installed is fine. If one is there it must load and run once."""
    path = Path(data_dir) / "models" / "segments.onnx"
    if not path.exists():
        return Check(AI_CHECK_NAME, True, f"not installed (optional; copy segments.onnx and segments.card.json to {path.parent})")
    try:
        import numpy as np
        from .ai.segmenter import ModelUnavailable, Segmenter
        segmenter = Segmenter.load(path)
        frame = np.random.default_rng(0).integers(0, 255, size=(96, 96)).astype(np.uint8)
        masks = segmenter.predict(frame)
        return Check(AI_CHECK_NAME, True, f"{path.name} loaded and predicted {masks.shape[0]} segment masks "
                                          f"(trained {segmenter.card.trained_at})")
    except Exception as exc:                         # a broken model must be visible, not hidden
        return Check(AI_CHECK_NAME, False, f"{path.name}: {exc}")


STENOSIS_CHECK_NAME = "AI stenosis model (optional)"


def check_stenosis_model(data_dir: Path) -> Check:
    """Optional like the segment model: none installed is fine; if one is there it must load and run once."""
    path = Path(data_dir) / "models" / "stenosis.onnx"
    if not path.exists():
        return Check(STENOSIS_CHECK_NAME, True,
                     f"not installed (optional; copy stenosis.onnx and stenosis.card.json to {path.parent})")
    try:
        import numpy as np
        from .ai.stenosis import StenosisFinder
        finder = StenosisFinder.load(path)
        frame = np.random.default_rng(0).integers(0, 255, size=(96, 96)).astype(np.uint8)
        found = finder.candidates(frame)
        return Check(STENOSIS_CHECK_NAME, True, f"{path.name} loaded; {len(found)} candidate(s) found on a test frame "
                                                f"(trained {finder.card.trained_at})")
    except Exception as exc:
        return Check(STENOSIS_CHECK_NAME, False, f"{path.name}: {exc}")


def run_selftest(data_dir: Path | None = None) -> list[Check]:
    """Run every check; a failure is reported, never raised. The last two checks look for the optional AI models
    in `data_dir` (default: the MUSSA-data folder of the current user)."""
    results = []
    for name, function in CHECKS:
        try:
            results.append(Check(name, True, function()))
        except Exception as exc:                      # any failure means this install is not usable
            results.append(Check(name, False, f"{type(exc).__name__}: {exc}"))
    folder = default_data_dir() if data_dir is None else Path(data_dir)
    results.append(check_ai_model(folder))
    results.append(check_stenosis_model(folder))
    return results


def format_report(results: list[Check]) -> str:
    lines = [f"{'OK    ' if r.ok else 'FAILED'}  {r.name}: {r.detail}" for r in results]
    failed = sum(not r.ok for r in results)
    lines.append("")
    lines.append(f"Self-test FAILED: {failed} of {len(results)} checks did not pass." if failed
                 else f"Self-test passed: all {len(results)} checks are fine.")
    return "\n".join(lines) + "\n"


def main() -> int:
    results = run_selftest()
    print(format_report(results))
    return 1 if any(not r.ok for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
