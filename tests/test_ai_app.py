import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from cagsyntax.ai.segment_names import SEGMENT_NAMES
from cagsyntax.ai.segmenter import ModelCard, ModelUnavailable
from tests.ai.toy_models import make_toy_model, write_card
from tests.test_scoring_flow import make_source, open_window, select_first


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeSegmenter:
    """Returns a known mask (segment "5" fills the top-left quarter) and counts predictions."""

    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail
        self.card = ModelCard("fake", "2026-11-21", 32, list(SEGMENT_NAMES), 0.5, None, "test")

    def predict(self, frame, threshold=0.5):
        self.calls += 1
        if self.fail:
            raise RuntimeError("model exploded")
        h, w = frame.shape
        masks = np.zeros((25, h, w), dtype=bool)
        masks[SEGMENT_NAMES.index("5"), : h // 2, : w // 2] = True
        return masks


def window(tmp_path, segmenter=None, select=True):
    from cagsyntax.app import MainWindow
    win = MainWindow(tmp_path / "data", segmenter=segmenter) if segmenter is not None else open_window(tmp_path, None)
    if select:
        win.import_from(make_source(tmp_path))
        select_first(win)
    return win


def test_without_a_model_the_viewer_works_and_the_overlay_explains_why(qapp, tmp_path):  # Review Focus 1
    win = window(tmp_path)
    win._warn = lambda text: (_ for _ in ()).throw(AssertionError("no dialog expected"))
    assert win.segmenter is None and "No AI segment model" in win.segmenter_error
    assert win.cine.frame_label.text() == "frame 1 / 5"                      # viewer unaffected
    assert win.toggle_ai_segments(True) is False
    assert "docs/ai-training.md" in win.statusBar().currentMessage()
    assert win.ai_action.isChecked() is False and not win.cine.overlay_visible()


def test_a_corrupt_model_file_gives_the_same_graceful_result(qapp, tmp_path):  # Review Focus 1
    models = tmp_path / "data" / "models"
    models.mkdir(parents=True)
    (models / "segments.onnx").write_bytes(b"garbage" * 40)
    write_card(models / "segments.onnx")
    win = window(tmp_path)
    assert win.segmenter is None and "not a valid ONNX" in win.segmenter_error
    assert win.toggle_ai_segments(True) is False and not win.cine.overlay_visible()
    assert win.cine.frame_label.text() == "frame 1 / 5"


def test_a_good_model_in_the_models_folder_is_loaded_and_draws_an_overlay(qapp, tmp_path):
    models = tmp_path / "data" / "models"
    models.mkdir(parents=True)
    make_toy_model(models / "segments.onnx", size=32, positive=(8, 9))
    write_card(models / "segments.onnx", size=32)
    win = window(tmp_path)
    assert win.segmenter is not None and win.segmenter_error == ""
    assert win.toggle_ai_segments(True) is True and win.cine.overlay_visible()
    assert win.ai_action.isChecked() is True


def test_overlay_refreshes_on_new_frames_uses_a_cache_and_turns_off(qapp, tmp_path):
    fake = FakeSegmenter()
    win = window(tmp_path, fake)
    assert win.toggle_ai_segments(True) is True
    assert fake.calls == 1 and win.cine.overlay_visible() and win.cine.overlay_caption()
    win.cine.step_fwd_btn.click()                                            # next frame: new prediction
    assert fake.calls == 2 and win.cine.overlay_visible()
    win.cine.back_btn.click()                                                # back to frame 1: cached
    assert fake.calls == 2 and win.cine.overlay_visible()
    win.toggle_ai_segments(False)
    assert not win.cine.overlay_visible() and win.ai_action.isChecked() is False
    win.cine.step_fwd_btn.click()
    assert fake.calls == 2 and not win.cine.overlay_visible()                # off: no work on frame changes
    win.toggle_ai_segments(True)
    assert fake.calls == 2 and win.cine.overlay_visible()                    # cached frame again


def test_nothing_is_predicted_while_the_cine_plays_and_it_refreshes_on_pause(qapp, tmp_path):
    fake = FakeSegmenter()
    win = window(tmp_path, fake)
    win.toggle_ai_segments(True)
    win.cine.play_btn.click()
    assert not win.cine.overlay_visible()
    for _ in range(3):
        win.cine._on_tick()                                                   # frames advance while playing
    assert fake.calls == 1 and not win.cine.overlay_visible()
    win.cine.play_btn.click()                                                 # pause
    assert fake.calls == 2 and win.cine.overlay_visible()


def test_a_failing_prediction_is_reported_and_leaves_the_overlay_off(qapp, tmp_path):
    fake = FakeSegmenter(fail=True)
    win = window(tmp_path, fake)
    warned = []
    win._warn = warned.append
    assert win.toggle_ai_segments(True) is False
    assert warned and "AI segments failed" in warned[0] and "model exploded" in warned[0]
    assert win.ai_action.isChecked() is False and not win.cine.overlay_visible()


def test_the_overlay_never_touches_scores_forms_or_stored_data(qapp, tmp_path):  # Review Focus 3
    fake = FakeSegmenter()
    win = window(tmp_path, fake)
    win.add_user("Dr Ana", "cardiologist")
    before = (win.store.case_summaries(), win.item_list.count(), [u.name for u in win.store.users()],
              sorted(p.name for p in (tmp_path / "data").iterdir()))
    win.toggle_ai_segments(True)
    win.cine.step_fwd_btn.click()
    win.toggle_ai_segments(False)
    after = (win.store.case_summaries(), win.item_list.count(), [u.name for u in win.store.users()],
             sorted(p.name for p in (tmp_path / "data").iterdir()))
    assert before == after


def test_switching_series_while_on_refreshes_for_the_new_series(qapp, tmp_path):
    fake = FakeSegmenter()
    win = window(tmp_path, fake)
    win.toggle_ai_segments(True)
    win.item_list.setCurrentRow(1)
    assert fake.calls == 2 and win.cine.overlay_visible()


# ---- review fixes: re-entrancy, stale overlays, model info ----
class HookSegmenter(FakeSegmenter):
    """Runs a callable inside the first prediction, as queued user input would during processEvents."""

    def __init__(self):
        super().__init__()
        self.hook = None

    def predict(self, frame, threshold=0.5):
        masks = super().predict(frame, threshold)
        hook, self.hook = self.hook, None
        if hook:
            hook()
        return masks


def test_a_slow_prediction_never_draws_over_a_frame_the_user_moved_to(qapp, tmp_path):
    seg = HookSegmenter()
    win = window(tmp_path, seg)
    seg.hook = lambda: win.cine.step_fwd_btn.click()           # the user steps on while frame 1 is being predicted
    assert win.toggle_ai_segments(True) is True
    assert win.cine.frame_index() == 1 and win.cine.overlay_visible()
    assert win._ai_drawn_key == (win._shown_uid, 1) and seg.calls == 2


def test_turning_the_overlay_off_during_a_prediction_leaves_it_off(qapp, tmp_path):
    seg = HookSegmenter()
    win = window(tmp_path, seg)
    win.toggle_ai_segments(True)                                # first (cached) frame drawn normally
    win.cine.step_fwd_btn.click()
    seg.hook = lambda: win.toggle_ai_segments(False)
    win.cine.step_fwd_btn.click()                               # new frame: the hook switches the overlay off mid-prediction
    assert not win.cine.overlay_visible() and win.ai_action.isChecked() is False


def test_pressing_play_during_a_prediction_leaves_no_overlay(qapp, tmp_path):
    seg = HookSegmenter()
    win = window(tmp_path, seg)
    seg.hook = lambda: win.cine.play_btn.click()
    win.toggle_ai_segments(True)
    assert win.cine.player.playing and not win.cine.overlay_visible()
    win.cine.play_btn.click()


def test_turning_the_overlay_on_says_which_model_is_shown(qapp, tmp_path):
    win = window(tmp_path, FakeSegmenter())
    win.toggle_ai_segments(True)
    msg = win.statusBar().currentMessage()
    assert "fake" in msg and "0.5" in msg                       # the card's trained_on and validation Dice
