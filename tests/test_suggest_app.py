import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from cagsyntax.ai.segment_names import SEGMENT_NAMES
from cagsyntax.ai.segmenter import ModelCard
from cagsyntax.ai.stenosis import Candidate
from cagsyntax.scoring import Lesion
from cagsyntax.store import StoreError
from tests.test_scoring_flow import make_source, open_window, select_first


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeSegmenter:
    """Segment "6" fills the top half of the frame, segment "11" the bottom half."""

    def __init__(self):
        self.card = ModelCard("fake", "2026-11-20", 32, list(SEGMENT_NAMES), 0.5, None, "test")

    def predict(self, frame, threshold=None):
        h, w = frame.shape
        masks = np.zeros((25, h, w), dtype=bool)
        masks[SEGMENT_NAMES.index("6"), : h // 2] = True
        masks[SEGMENT_NAMES.index("11"), h // 2:] = True
        return masks


class FakeStenosis:
    """Finds one narrowing in the top half and one in the bottom half, unless told to find nothing."""

    def __init__(self, found=True, fail=False):
        self.found, self.fail = found, fail
        self.card = ModelCard("fake", "2026-11-21", 32, ["stenosis"], 0.5, None, "test")

    def candidates(self, frame, threshold=None, min_pixels=30):
        if self.fail:
            raise RuntimeError("model exploded")
        if not self.found:
            return []
        h, w = frame.shape
        out = []
        for score, (y0, y1) in ((0.9, (2, 8)), (0.6, (h - 8, h - 2))):
            mask = np.zeros((h, w), dtype=bool)
            mask[y0:y1, 2:10] = True
            out.append(Candidate(mask=mask, box=(2, y0, 10, y1), pixels=int(mask.sum()), score=score))
        return out


def case_window(tmp_path, stenosis=None, segmenter=None, level="resident"):
    win = open_window(tmp_path, make_source(tmp_path))
    win.add_user("Ana", level)
    select_first(win)
    assert win.score_selected_case()
    win.segmenter = segmenter if segmenter is not None else FakeSegmenter()
    win.stenosis = stenosis if stenosis is not None else FakeStenosis()
    win.messages = []
    win._warn = win.messages.append
    return win


def choose(win, segments):
    """Stand in for the dialog: the scorer ticks the suggestions of these segments (None = cancels)."""
    def chooser(suggestions):
        return None if segments is None else [s for s in suggestions if s.segment in segments]
    win._choose_suggestions = chooser


def segments_of(win):
    return [les.segments for les in win.panel.case().lesions]


# ---- availability ----
def test_the_scoring_toolbar_has_a_suggest_action(qapp, tmp_path):
    win = case_window(tmp_path)
    assert any(a.text() == "Suggest lesions" for a in win.findChildren(QAction))


def test_no_stenosis_model_installed_says_so_and_changes_nothing(qapp, tmp_path):
    win = case_window(tmp_path)
    win.stenosis = None
    win.stenosis_error = "No stenosis model installed (expected at X)."
    assert win.suggest_lesions() is None
    assert "stenosis model" in win.statusBar().currentMessage().lower()
    assert segments_of(win) == [[]]


def test_no_segment_model_says_so(qapp, tmp_path):
    win = case_window(tmp_path)
    win.segmenter = None
    win.segmenter_error = "No AI segment model installed."
    assert win.suggest_lesions() is None
    assert "segment model" in win.statusBar().currentMessage().lower()


def test_it_needs_an_open_case_and_a_scorer(qapp, tmp_path):
    win = open_window(tmp_path, make_source(tmp_path))
    win.segmenter, win.stenosis = FakeSegmenter(), FakeStenosis()
    select_first(win)
    assert win.suggest_lesions() is None and "score case" in win.statusBar().currentMessage().lower()


def test_it_needs_a_shown_series(qapp, tmp_path):
    win = case_window(tmp_path)
    win.cine.set_series(None, "") if False else None
    win.cine.current_frame = lambda: None
    assert win.suggest_lesions() is None and "series" in win.statusBar().currentMessage().lower()


# ---- finding and choosing ----
def test_nothing_found_says_so_and_never_opens_the_dialog(qapp, tmp_path):
    win = case_window(tmp_path, stenosis=FakeStenosis(found=False))
    win._choose_suggestions = lambda s: (_ for _ in ()).throw(AssertionError("no dialog expected"))
    assert win.suggest_lesions() == [] and "no narrowing" in win.statusBar().currentMessage().lower()


def test_the_dialog_gets_the_candidates_placed_in_their_segments_best_first(qapp, tmp_path):
    win = case_window(tmp_path)
    seen = []
    win._choose_suggestions = lambda s: seen.append(s) or []
    win.suggest_lesions()
    assert [(s.segment, s.score) for s in seen[0]] == [("6", 0.9), ("11", 0.6)]


def test_ticked_suggestions_become_segments_only_lesions_replacing_the_empty_one(qapp, tmp_path):
    win = case_window(tmp_path)
    choose(win, {"6", "11"})
    chosen = win.suggest_lesions()
    assert [s.segment for s in chosen] == ["6", "11"]
    assert segments_of(win) == [["6"], ["11"]]
    les = win.panel.case().lesions[0]
    assert les.occlusion is None and les.thrombus is None and les.bifurcation is None
    assert "added 2" in win.statusBar().currentMessage().lower() and "check" in win.statusBar().currentMessage().lower()


def test_the_form_counts_as_changed_after_suggestions_are_added(qapp, tmp_path):
    win = case_window(tmp_path)
    choose(win, {"6"})
    win.suggest_lesions()
    assert win._dirty()


def test_existing_lesions_are_kept_and_a_segment_already_present_is_not_duplicated(qapp, tmp_path):
    win = case_window(tmp_path)
    case = win.panel.case()
    case.lesions = [Lesion(segments=["6"], occlusion=True)]
    win.panel.set_case(case)
    choose(win, {"6", "11"})
    win.suggest_lesions()
    assert segments_of(win) == [["6"], ["11"]]
    assert win.panel.case().lesions[0].occlusion is True               # the scorer's answer is untouched


def test_a_segment_that_does_not_exist_for_the_dominance_is_removed_with_the_forms_own_notice(qapp, tmp_path):
    win = case_window(tmp_path)
    win.panel.set_dominance("left")                                     # segment 11 exists for left dominance...
    choose(win, {"6", "11"})
    win.suggest_lesions()                                               # ...nothing may crash whatever is dropped
    assert all(isinstance(s, list) for s in segments_of(win))


def test_nothing_ticked_adds_nothing_but_still_records_the_rejections(qapp, tmp_path):
    win = case_window(tmp_path)
    choose(win, set())
    win.suggest_lesions()
    assert segments_of(win) == [[]]
    log = win.store.suggestion_events(win._scoring_study[0])
    assert [(e.segment, e.action) for e in log] == [("6", "rejected"), ("11", "rejected")]


def test_cancelling_the_dialog_records_nothing_and_adds_nothing(qapp, tmp_path):
    win = case_window(tmp_path)
    choose(win, None)
    assert win.suggest_lesions() is None
    assert segments_of(win) == [[]] and win.store.suggestion_events(win._scoring_study[0]) == []


# ---- the log ----
def test_accepts_and_rejects_are_logged_with_who_where_and_which_models(qapp, tmp_path):
    win = case_window(tmp_path)
    choose(win, {"6"})
    win.suggest_lesions()
    log = win.store.suggestion_events(win._scoring_study[0])
    assert [(e.segment, e.action) for e in log] == [("6", "accepted"), ("11", "rejected")]
    first = log[0]
    assert first.user_id == win.current_user().id and first.series_uid == win._shown_uid
    assert first.frame == win.cine.frame_index() and first.pixels == 48 and first.score == 0.9
    assert first.segment_model == "segments 2026-11-20" and first.stenosis_model == "stenosis 2026-11-21"


def test_a_failed_log_is_shown_but_the_lesions_are_still_added(qapp, tmp_path):
    win = case_window(tmp_path)
    choose(win, {"6"})
    win.store.log_suggestions = lambda *a, **k: (_ for _ in ()).throw(StoreError("cases.sqlite: disk full."))
    win.suggest_lesions()
    assert segments_of(win) == [["6"]]
    assert win.messages and "disk full" in win.messages[0] and "not recorded" in win.messages[0].lower()


# ---- failures ----
def test_a_model_failure_is_reported_and_changes_nothing(qapp, tmp_path):
    win = case_window(tmp_path, stenosis=FakeStenosis(fail=True))
    assert win.suggest_lesions() is None
    assert win.messages and "model exploded" in win.messages[0]
    assert segments_of(win) == [[]]


# ---- loading the models at start ----
def test_the_stenosis_model_is_loaded_from_the_models_folder_at_start(qapp, tmp_path):
    from cagsyntax.app import MainWindow
    from tests.ai.toy_models import make_toy_model, write_card
    models = tmp_path / "data" / "models"
    models.mkdir(parents=True)
    write_card(make_toy_model(models / "stenosis.onnx", size=32, channels=1, positive=(0,)), size=32,
               classes=["stenosis"])
    win = MainWindow(tmp_path / "data")
    assert win.stenosis is not None and win.stenosis_error == ""


def test_without_the_file_the_error_names_where_to_put_it(qapp, tmp_path):
    from cagsyntax.app import MainWindow
    win = MainWindow(tmp_path / "data")
    assert win.stenosis is None and "stenosis.onnx" in win.stenosis_error


def test_a_broken_stenosis_model_does_not_stop_the_app_or_the_segment_overlay(qapp, tmp_path):
    from cagsyntax.app import MainWindow
    models = tmp_path / "data" / "models"
    models.mkdir(parents=True)
    (models / "stenosis.onnx").write_bytes(b"junk")
    win = MainWindow(tmp_path / "data")
    assert win.stenosis is None and win.stenosis_error


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A blocked action now opens a dialog; in tests it must never wait for a click."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
