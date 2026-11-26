import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess
import sys
from pathlib import Path

from cagsyntax import selftest

ROOT = Path(__file__).resolve().parents[1]


def test_every_check_passes_on_a_working_install():
    results = selftest.run_selftest()
    names = [r.name for r in results]
    assert {"Qt (PySide6)", "DICOM JPEG Lossless decoder", "DICOM JPEG Baseline decoder",
            "ONNX Runtime (CPU)", "Image library (Pillow)", "SQLite", "Scoring engine"} <= set(names)
    failed = [(r.name, r.detail) for r in results if not r.ok]
    assert failed == []


def test_a_failing_check_is_reported_not_raised(monkeypatch):
    def boom():
        raise ImportError("No module named 'onnxruntime'")
    monkeypatch.setattr(selftest, "_check_onnxruntime", boom)
    results = selftest.run_selftest()
    bad = [r for r in results if not r.ok]
    assert [r.name for r in bad] == ["ONNX Runtime (CPU)"] and "onnxruntime" in bad[0].detail


def test_the_scoring_engine_check_uses_a_known_answer():
    assert selftest._check_scoring_engine() == "a single mid-LAD stenosis scores 2.0"


def test_format_report_lists_each_check_and_the_verdict():
    ok = selftest.Check("A", True, "fine")
    bad = selftest.Check("B", False, "missing")
    text = selftest.format_report([ok, bad])
    assert "OK" in text and "FAILED" in text and "A" in text and "missing" in text
    assert text.rstrip().endswith("Self-test FAILED: 1 of 2 checks did not pass.")
    assert selftest.format_report([ok]).rstrip().endswith("Self-test passed: all 1 checks are fine.")


def test_the_selftest_command_line_exits_zero_when_all_is_well():
    done = subprocess.run([sys.executable, "-m", "cagsyntax.selftest"], cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "QT_QPA_PLATFORM": "offscreen"},
                          timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Self-test passed" in done.stdout


# ---- the optional AI model ----
def test_no_model_installed_is_fine_and_says_how_to_add_it(tmp_path):
    check = selftest.check_ai_model(tmp_path)
    assert check.ok and "not installed" in check.detail and "segments.onnx" in check.detail


def test_a_working_model_is_loaded_and_run_once(tmp_path):
    from tests.ai.toy_models import make_toy_model, write_card
    models = tmp_path / "models"
    models.mkdir()
    write_card(make_toy_model(models / "segments.onnx", size=32), size=32)
    check = selftest.check_ai_model(tmp_path)
    assert check.ok and "predicted" in check.detail


def test_a_broken_model_fails_with_the_reason(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    (models / "segments.onnx").write_bytes(b"not a model")
    check = selftest.check_ai_model(tmp_path)
    assert not check.ok and "segments.onnx" in check.detail


def test_run_selftest_includes_both_ai_checks_for_the_given_data_folder(tmp_path):
    results = {r.name: r for r in selftest.run_selftest(tmp_path)}
    assert results["AI segment model (optional)"].ok and results["AI stenosis model (optional)"].ok


def test_no_stenosis_model_is_fine_and_says_where_to_put_it(tmp_path):
    check = selftest.check_stenosis_model(tmp_path)
    assert check.ok and "not installed" in check.detail and "stenosis.onnx" in check.detail


def test_a_working_stenosis_model_is_loaded_and_run_once(tmp_path):
    from tests.ai.toy_models import make_toy_model, write_card
    models = tmp_path / "models"
    models.mkdir()
    write_card(make_toy_model(models / "stenosis.onnx", size=32, channels=1, positive=(0,)), size=32, classes=["stenosis"])
    check = selftest.check_stenosis_model(tmp_path)
    assert check.ok and "found" in check.detail


def test_a_broken_stenosis_model_fails_with_the_reason(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    (models / "stenosis.onnx").write_bytes(b"not a model")
    check = selftest.check_stenosis_model(tmp_path)
    assert not check.ok and "stenosis.onnx" in check.detail


def test_the_diagram_image_check_passes_and_is_listed():
    results = selftest.run_selftest()
    row = next(r for r in results if r.name == "Diagram image (artery map)")
    assert row.ok, row.detail
    assert "1200x1200" in row.detail
