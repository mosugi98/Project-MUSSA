"""Check that this install of MUSSA can do its job. Run it on a new PC, or after packaging:

    python -m cagsyntax.selftest          (or  MUSSA.exe --selftest)

It touches no patient data and opens no window. Each check reports OK or FAILED with the reason."""
from __future__ import annotations

import sys
from dataclasses import dataclass


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


CHECKS = (
    ("Qt (PySide6)", lambda: _check_qt()),
    ("DICOM JPEG Lossless decoder", lambda: _check_jpeg_lossless()),
    ("DICOM JPEG Baseline decoder", lambda: _check_jpeg_baseline()),
    ("ONNX Runtime (CPU)", lambda: _check_onnxruntime()),
    ("Image library (Pillow)", lambda: _check_pillow()),
    ("SQLite", lambda: _check_sqlite()),
    ("Scoring engine", lambda: _check_scoring_engine()),
)


def run_selftest() -> list[Check]:
    """Run every check; a failure is reported, never raised."""
    results = []
    for name, function in CHECKS:
        try:
            results.append(Check(name, True, function()))
        except Exception as exc:                      # any failure means this install is not usable
            results.append(Check(name, False, f"{type(exc).__name__}: {exc}"))
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
