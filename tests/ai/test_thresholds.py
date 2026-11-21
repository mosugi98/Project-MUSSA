import json

import numpy as np
import pytest

from cagsyntax.ai.arcade import ArcadeSplit
from cagsyntax.ai.segment_names import SEGMENT_NAMES
from cagsyntax.ai.segmenter import ModelUnavailable, Segmenter
from cagsyntax.ai.thresholds import DEFAULT_GRID, ThresholdResult, tune_thresholds, write_thresholds
from tests.ai.test_arcade import make_split
from tests.ai.toy_models import make_toy_model, write_card


def frame(h=64, w=64):
    return np.random.default_rng(0).integers(0, 255, size=(h, w)).astype(np.uint8)


def toy(tmp_path, positive=(3,), logit=0.85, **card):
    model = make_toy_model(tmp_path / "segments.onnx", size=32, positive=positive, logit=logit)   # sigmoid(0.85) ~ 0.70
    write_card(model, size=32, **card)
    return model


# ---- probabilities and per-segment thresholds on the card ----
def test_probabilities_are_returned_in_the_frames_size_and_range(tmp_path):
    seg = Segmenter.load(toy(tmp_path))
    p = seg.probabilities(frame(50, 40))
    assert p.shape == (25, 50, 40) and p.dtype == np.float32
    assert 0.0 <= p.min() and p.max() <= 1.0
    assert p[3].mean() == pytest.approx(1 / (1 + np.exp(-0.85)), abs=1e-3)


def test_a_card_without_thresholds_uses_one_half_for_every_segment(tmp_path):
    seg = Segmenter.load(toy(tmp_path))
    assert seg.thresholds == [0.5] * 25
    assert seg.predict(frame())[3].all()


def test_card_thresholds_are_used_per_segment_by_default(tmp_path):
    name = SEGMENT_NAMES[3]
    seg = Segmenter.load(toy(tmp_path, thresholds={name: 0.8}))                  # above the 0.70 the model outputs
    assert seg.thresholds[3] == 0.8 and seg.thresholds[0] == 0.5
    assert not seg.predict(frame()).any()
    assert seg.predict(frame(), threshold=0.5)[3].all()                          # an explicit value overrides the card


def test_a_lower_card_threshold_rescues_a_weak_segment(tmp_path):
    model = make_toy_model(tmp_path / "segments.onnx", size=32, positive=(3,), logit=-1.0)    # sigmoid ~ 0.27
    write_card(model, size=32, thresholds={SEGMENT_NAMES[3]: 0.2})
    assert Segmenter.load(model).predict(frame())[3].all()


@pytest.mark.parametrize("bad", [{"5": 0.0}, {"5": 1.0}, {"5": "high"}, {"nope": 0.3}, [0.5], {"5": True}])
def test_invalid_card_thresholds_make_the_model_unavailable(tmp_path, bad):
    with pytest.raises(ModelUnavailable) as exc:
        Segmenter.load(toy(tmp_path, thresholds=bad))
    assert "threshold" in str(exc.value).lower()


# ---- tuning ----
class FakeSegmenter:
    """probabilities() returns prepared arrays in call order."""

    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), 0

    def probabilities(self, frame):
        out = self.outputs[self.calls]
        self.calls += 1
        return out


@pytest.fixture
def split(tmp_path):
    return ArcadeSplit(make_split(tmp_path))


def weak_but_right(split, level):
    """Probabilities equal to `level` inside every true mask and 0.01 elsewhere."""
    outs = []
    for i in range(len(split)):
        truth = split.load_masks(i)
        outs.append(np.where(truth, np.float32(level), np.float32(0.01)).astype(np.float32))
    return outs


def test_a_weak_but_correct_segment_gets_a_lower_threshold_and_a_better_score(split):
    result = tune_thresholds(FakeSegmenter(weak_but_right(split, 0.3)), split)
    assert isinstance(result, ThresholdResult)
    assert result.before_macro_dice == 0.0                                       # nothing passes 0.5
    assert result.after_macro_dice == pytest.approx(1.0)
    five = SEGMENT_NAMES.index("5")
    assert result.thresholds["5"] <= 0.3 and result.per_segment["5"]["after"] == pytest.approx(1.0)
    assert result.per_segment["5"]["before"] == 0.0


def test_segments_that_are_never_present_keep_the_default_threshold(split):
    result = tune_thresholds(FakeSegmenter(weak_but_right(split, 0.3)), split)
    assert result.thresholds["1"] == 0.5 and result.per_segment["1"]["after"] is None
    assert set(result.thresholds) == set(SEGMENT_NAMES)


def test_a_segment_that_is_already_right_keeps_a_threshold_near_one_half(split):
    result = tune_thresholds(FakeSegmenter(weak_but_right(split, 0.9)), split)
    assert result.before_macro_dice == pytest.approx(1.0)
    assert 0.3 <= result.thresholds["5"] <= 0.6                                  # ties go to the value closest to 0.5
    assert result.after_macro_dice == pytest.approx(1.0)


def test_tuning_never_scores_worse_than_the_default(split):
    rng = np.random.default_rng(1)
    noisy = [rng.random((25, 64, 64)).astype(np.float32) for _ in range(len(split))]
    result = tune_thresholds(FakeSegmenter(noisy), split)
    assert result.after_macro_dice >= result.before_macro_dice


def test_limit_and_progress_are_respected(split):
    seen = []
    fake = FakeSegmenter(weak_but_right(split, 0.3))
    result = tune_thresholds(fake, split, limit=1, progress=lambda d, t: seen.append((d, t)))
    assert fake.calls == 1 and result.images == 1 and seen == [(1, 1)]


def test_the_grid_is_sorted_and_inside_zero_and_one():
    assert list(DEFAULT_GRID) == sorted(DEFAULT_GRID) and 0 < DEFAULT_GRID[0] and DEFAULT_GRID[-1] < 1
    assert 0.5 in DEFAULT_GRID


def test_a_probability_array_of_the_wrong_shape_is_refused(split):
    with pytest.raises(ValueError):
        tune_thresholds(FakeSegmenter([np.zeros((25, 10, 10), np.float32)] * 2), split)


# ---- writing the result into the card ----
def test_write_thresholds_updates_the_card_and_keeps_everything_else(tmp_path):
    model = toy(tmp_path, extra_field="keep me")
    result = ThresholdResult(thresholds={n: (0.3 if n == "5" else 0.5) for n in SEGMENT_NAMES}, images=10,
                             before_macro_dice=0.2, after_macro_dice=0.3, per_segment={}, split="val")
    card_path = write_thresholds(model, result)
    card = json.loads(card_path.read_text(encoding="utf-8"))
    assert card["thresholds"]["5"] == 0.3 and card["extra_field"] == "keep me" and card["trained_on"] == "toy test model"
    assert card["thresholds_tuned_on"] == "val (10 images)"
    assert Segmenter.load(model).thresholds[SEGMENT_NAMES.index("5")] == 0.3


def test_write_thresholds_does_not_touch_a_missing_or_broken_card(tmp_path):
    model = make_toy_model(tmp_path / "segments.onnx", size=32)
    with pytest.raises(ModelUnavailable):
        write_thresholds(model, ThresholdResult({}, 0, 0.0, 0.0, {}, "val"))
    (tmp_path / "segments.card.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(ModelUnavailable):
        write_thresholds(model, ThresholdResult({}, 0, 0.0, 0.0, {}, "val"))
    assert (tmp_path / "segments.card.json").read_text(encoding="utf-8") == "{broken"
