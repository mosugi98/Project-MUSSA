import numpy as np
import pytest

from cagsyntax.ai.metrics import dice, iou, per_segment_scores
from cagsyntax.ai.segment_names import SEGMENT_NAMES


def box(rows, cols, size=20):
    m = np.zeros((size, size), dtype=bool)
    m[rows[0]:rows[1], cols[0]:cols[1]] = True
    return m


def test_dice_and_iou_for_identical_disjoint_and_half_overlapping_masks():
    a = box((0, 10), (0, 10))
    assert dice(a, a) == 1.0 and iou(a, a) == 1.0
    assert dice(a, box((10, 20), (10, 20))) == 0.0 and iou(a, box((10, 20), (10, 20))) == 0.0
    half = box((0, 10), (5, 15))                           # shares half of each mask
    assert dice(a, half) == pytest.approx(0.5) and iou(a, half) == pytest.approx(1 / 3)


def test_both_empty_is_none_but_a_missed_or_false_segment_is_zero():
    empty = np.zeros((20, 20), dtype=bool)
    assert dice(empty, empty) is None and iou(empty, empty) is None
    a = box((0, 5), (0, 5))
    assert dice(empty, a) == 0.0 and dice(a, empty) == 0.0          # predicted nothing / predicted only


def test_per_segment_scores_order_and_pixel_counts():
    truths = np.zeros((25, 20, 20), dtype=bool)
    preds = np.zeros((25, 20, 20), dtype=bool)
    truths[8] = box((0, 10), (0, 10))                      # segment "5"
    preds[8] = box((0, 10), (5, 15))
    preds[9] = box((0, 4), (0, 4))                         # a false positive for segment "6"
    scores = per_segment_scores(preds, truths)
    assert list(scores) == list(SEGMENT_NAMES) and len(scores) == 25
    assert scores["5"] == {"dice": pytest.approx(0.5), "iou": pytest.approx(1 / 3), "truth_pixels": 100, "pred_pixels": 100}
    assert scores["6"]["dice"] == 0.0 and scores["6"]["pred_pixels"] == 16 and scores["6"]["truth_pixels"] == 0
    assert scores["1"] == {"dice": None, "iou": None, "truth_pixels": 0, "pred_pixels": 0}


def test_shape_mismatch_is_rejected():
    with pytest.raises(ValueError):
        dice(np.zeros((4, 4), dtype=bool), np.zeros((5, 5), dtype=bool))
    with pytest.raises(ValueError):
        per_segment_scores(np.zeros((24, 4, 4), dtype=bool), np.zeros((24, 4, 4), dtype=bool))
