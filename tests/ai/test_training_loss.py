"""The training loss. PyTorch is only installed in the cloud training environment, so these tests are skipped
on a normal PC and run there (and in the throwaway smoke-test environment)."""
import importlib.util
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("train_segmentation", ROOT / "tools" / "training" / "train_segmentation.py")
train = importlib.util.module_from_spec(spec)
import sys
sys.path.insert(0, str(ROOT / "src"))
spec.loader.exec_module(train)

C = 25


def batch(present=(3,), size=16, n=2):
    y = torch.zeros(n, C, size, size)
    for c in present:
        y[:, c, 4:12, 4:12] = 1.0
    return y


def logits_for(y, right=True, scale=8.0):
    """Confident logits: correct when right, everything-negative when not."""
    return (y * 2 - 1) * scale if right else torch.full_like(y, -scale)


def test_predicting_nothing_for_a_present_segment_costs_much_more_than_predicting_it():
    y = batch()
    good = train.segmentation_loss(logits_for(y, True), y, torch)
    empty = train.segmentation_loss(logits_for(y, False), y, torch)
    assert empty > good + 0.8                                   # collapsing to "empty" must never look attractive


def test_absent_segments_add_no_dice_reward_for_predicting_nothing():
    """The old per-image dice gave a perfect score to an empty prediction of an absent segment, which pulled
    the model towards empty masks. With no segment present the loss is just the cross-entropy term."""
    y = torch.zeros(2, C, 16, 16)
    loss = train.segmentation_loss(torch.full_like(y, -8.0), y, torch)
    assert torch.isfinite(loss) and loss < 0.01


def test_a_rare_segment_counts_as_much_as_a_common_one_in_the_dice_term():
    y = batch(present=(3, 9))
    y[:, 9] = 0
    y[:, 9, 8, 8] = 1.0                                         # a tiny segment: one pixel per image
    right = logits_for(y, True)
    wrong_rare = right.clone()
    wrong_rare[:, 9] = -8.0                                     # only the rare one is missed
    assert train.segmentation_loss(wrong_rare, y, torch) > train.segmentation_loss(right, y, torch) + 0.2


def test_a_higher_positive_weight_punishes_missed_pixels_more():
    y = batch()
    miss = logits_for(y, False)
    assert train.segmentation_loss(miss, y, torch, pos_weight=10.0) > train.segmentation_loss(miss, y, torch, pos_weight=1.0)


def test_gradients_are_finite_and_point_towards_the_truth():
    y = batch()
    logits = torch.full_like(y, -2.0, requires_grad=True)
    train.segmentation_loss(logits, y, torch).backward()
    assert torch.isfinite(logits.grad).all()
    assert logits.grad[:, 3, 6, 6].max() < 0                    # inside the true mask: raise the logit
    assert logits.grad[:, 0, 6, 6].max() >= 0                   # an absent segment: do not raise it


def test_early_stopping_helper_stops_after_the_patience_without_improvement():
    assert train.should_stop([0.1, 0.2, 0.3], patience=3) is False
    assert train.should_stop([0.1, 0.3, 0.2, 0.25, 0.1], patience=3) is True
    assert train.should_stop([0.3, 0.2], patience=3) is False
    assert train.should_stop([0.3, 0.2, 0.1], patience=0) is False          # 0 turns early stopping off
