import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from cagsyntax.ai.arcade import ArcadeSplit
from cagsyntax.ai.evaluate import EvalReport, evaluate_model, report_to_json, report_to_markdown
from cagsyntax.ai.segment_names import SEGMENT_NAMES
from tests.ai.test_arcade import make_split
from tests.ai.toy_models import make_toy_model, write_card

ROOT = Path(__file__).resolve().parents[2]


class Fake:
    """Returns prepared masks in call order, so tests control exactly what is 'predicted'."""

    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), 0

    def predict(self, frame, threshold=0.5):
        out = self.outputs[self.calls]
        self.calls += 1
        return out


def truths(split, n=None):
    return [split.load_masks(i) for i in range(n or len(split))]


@pytest.fixture
def split(tmp_path):
    return ArcadeSplit(make_split(tmp_path))


def test_a_perfect_model_scores_one_on_every_present_segment(split):
    report = evaluate_model(Fake(truths(split)), split)
    assert isinstance(report, EvalReport) and report.images == 2 and report.split == "train"
    assert report.macro_dice == pytest.approx(1.0) and report.macro_iou == pytest.approx(1.0)
    assert report.segments_evaluated == 3                                  # "5", "6" and "9a" occur
    assert report.per_segment["5"]["dice"] == pytest.approx(1.0)
    assert report.per_segment["1"] == {"dice": None, "iou": None, "truth_pixels": 0, "pred_pixels": 0}


def test_a_model_that_predicts_nothing_scores_zero_on_present_segments(split):
    empty = [np.zeros_like(t) for t in truths(split)]
    report = evaluate_model(Fake(empty), split)
    assert report.macro_dice == 0.0 and report.segments_evaluated == 3
    assert report.per_segment["6"]["dice"] == 0.0 and report.per_segment["6"]["truth_pixels"] > 0


def test_half_of_each_mask_gives_a_dice_of_about_two_thirds(split):
    halves = []
    for t in truths(split):
        h = np.zeros_like(t)
        for c in range(t.shape[0]):
            cols = np.nonzero(t[c].any(axis=0))[0]
            if len(cols):
                cut = (cols.min() + cols.max()) // 2
                h[c][:, :cut + 1] = t[c][:, :cut + 1]
        halves.append(h)
    report = evaluate_model(Fake(halves), split)
    assert report.per_segment["5"]["dice"] == pytest.approx(2 / 3, abs=0.06)


def test_scores_pool_pixels_over_images_instead_of_averaging_per_image(tmp_path):
    root = make_split(tmp_path)
    ann = json.loads((root / "annotations" / "train.json").read_text())
    ann["annotations"] = [
        {"id": 1, "image_id": 1, "category_id": 1, "segmentation": [[5, 5, 45, 5, 45, 45, 5, 45]]},    # big "5"
        {"id": 2, "image_id": 2, "category_id": 1, "segmentation": [[5, 5, 9, 5, 9, 9, 5, 9]]},        # tiny "5"
    ]
    (root / "annotations" / "train.json").write_text(json.dumps(ann))
    split = ArcadeSplit(root)
    t = truths(split)
    outputs = [t[0], np.zeros_like(t[1])]                      # perfect on the big one, nothing on the tiny one
    report = evaluate_model(Fake(outputs), split)
    seg = report.per_segment["5"]
    pooled = 2 * seg["pred_pixels"] / (seg["pred_pixels"] + seg["truth_pixels"])
    assert seg["dice"] == pytest.approx(pooled) and seg["dice"] != pytest.approx(0.5, abs=0.01)
    assert seg["dice"] > 0.9


def test_absent_segments_are_left_out_of_the_macro_average(split):
    report = evaluate_model(Fake(truths(split)), split)
    present = [v["dice"] for v in report.per_segment.values() if v["dice"] is not None]
    assert report.macro_dice == pytest.approx(sum(present) / len(present)) and len(present) == report.segments_evaluated


def test_limit_evaluates_only_the_first_images_and_progress_is_reported(split):
    seen = []
    fake = Fake(truths(split, 1))
    report = evaluate_model(fake, split, limit=1, progress=lambda done, total: seen.append((done, total)))
    assert report.images == 1 and fake.calls == 1 and seen == [(1, 1)]


def test_a_prediction_of_the_wrong_shape_is_rejected(split):
    with pytest.raises(ValueError, match="shape"):
        evaluate_model(Fake([np.zeros((24, 64, 64), dtype=bool)] * 2), split)


def test_markdown_and_json_reports_list_all_25_segments_in_order(split):
    report = evaluate_model(Fake(truths(split)), split)
    md = report_to_markdown(report)
    rows = [line.split("|")[1].strip() for line in md.splitlines() if line.startswith("| ") and line.split("|")[1].strip() in SEGMENT_NAMES]
    assert rows == list(SEGMENT_NAMES)
    assert "macro" in md.lower() and "train" in md
    data = report_to_json(report)
    assert data["images"] == 2 and list(data["per_segment"]) == list(SEGMENT_NAMES) and data["macro_dice"] == pytest.approx(1.0)
    json.dumps(data)                                           # serialisable


def test_the_command_line_tool_runs_end_to_end_with_a_toy_model(tmp_path):
    root = make_split(tmp_path)
    model = make_toy_model(tmp_path / "segments.onnx", size=32, positive=(8, 9))
    write_card(model, size=32)
    out = tmp_path / "report"
    result = subprocess.run([sys.executable, str(ROOT / "tools" / "ai" / "evaluate_segmentation.py"),
                             "--model", str(model), "--split", str(root), "--out", str(out)],
                            capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert data["images"] == 2 and "5" in data["per_segment"]
    assert (out / "report.md").read_text(encoding="utf-8").startswith("# Segment model evaluation")
    assert "macro" in result.stdout.lower()
    bad = subprocess.run([sys.executable, str(ROOT / "tools" / "ai" / "evaluate_segmentation.py"),
                          "--model", str(tmp_path / "missing.onnx"), "--split", str(root), "--out", str(out)],
                         capture_output=True, text=True, cwd=tmp_path)
    assert bad.returncode != 0 and "No model file" in bad.stderr
