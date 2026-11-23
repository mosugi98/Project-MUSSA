import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from pathlib import Path

import pydicom
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QDialog

from cagsyntax.app import PATH_ROLE
from cagsyntax.ui.proposal_dialog import ProposalDialog
from tests.test_scoring_flow import make_source, open_window, select_first
from tests.test_suggest_app import FakeSegmenter, FakeStenosis, case_window


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def choose(win, ids):
    """Stand in for the dialog: the scorer ticks these lesion ids (None = cancels). Keeps what was proposed."""
    win.proposed = []

    def chooser(run):
        win.proposed.append(run)
        return None if ids is None else [i for i in run.proposed_ids() if i in ids]
    win._choose_proposals = chooser


def segments_of(win):
    return [les.segments for les in win.panel.case().lesions]


# ---- availability ----
def test_the_scoring_toolbar_has_a_run_ai_on_study_action(qapp, tmp_path):
    win = case_window(tmp_path)
    assert any(a.text() == "Run AI on study" for a in win.findChildren(QAction))


def test_it_needs_an_open_case_and_a_scorer(qapp, tmp_path):
    win = open_window(tmp_path, make_source(tmp_path))
    win.segmenter, win.stenosis = FakeSegmenter(), FakeStenosis()
    select_first(win)
    assert win.run_ai_on_study() is None and "score case" in win.statusBar().currentMessage().lower()


def test_missing_models_are_named_and_nothing_changes(qapp, tmp_path):
    win = case_window(tmp_path)
    win.stenosis, win.stenosis_error = None, "No stenosis model installed (expected at X)."
    assert win.run_ai_on_study() is None and "stenosis model" in win.statusBar().currentMessage().lower()
    (tmp_path / "b").mkdir()
    win = case_window(tmp_path / "b")
    win.segmenter, win.segmenter_error = None, "No AI segment model installed."
    assert win.run_ai_on_study() is None and "segment model" in win.statusBar().currentMessage().lower()
    assert segments_of(win) == [[]]


# ---- running and choosing ----
def test_the_whole_study_is_analysed_and_the_dialog_gets_one_lesion_per_segment(qapp, tmp_path):
    win = case_window(tmp_path)
    choose(win, set())
    assert win.run_ai_on_study() == []
    run = win.proposed[0]
    assert len(run.runs) == 2 and run.proposed_ids() == ["AI_6", "AI_11"]        # both series, merged per segment


def test_ticked_proposals_become_segments_only_lesions_and_dominance_stays_the_scorers(qapp, tmp_path):
    win = case_window(tmp_path)
    win.panel.set_dominance("left")
    choose(win, {"AI_6", "AI_11"})
    assert win.run_ai_on_study() == ["AI_6", "AI_11"]
    assert segments_of(win) == [["6"], ["11"]]
    les = win.panel.case().lesions[0]
    assert les.occlusion is None and les.thrombus is None and les.bifurcation is None
    assert win.panel.case().dominance == "left"
    assert "check each one" in win.statusBar().currentMessage().lower()


def test_cancelling_adds_nothing_and_records_nothing(qapp, tmp_path):
    win = case_window(tmp_path)
    choose(win, None)
    assert win.run_ai_on_study() is None
    assert segments_of(win) == [[]] and win.store.ai_runs(win._scoring_study[0]) == []


def test_the_raw_proposal_is_kept_with_what_was_taken_and_the_models(qapp, tmp_path):
    win = case_window(tmp_path)
    choose(win, {"AI_6"})
    win.run_ai_on_study()
    (row,) = win.store.ai_runs(win._scoring_study[0])
    assert row.proposed == ["AI_6", "AI_11"] and row.accepted == ["AI_6"] and row.user_id == win.current_user().id
    assert row.segment_model.startswith("segments ") and row.stenosis_model.startswith("stenosis ")
    data = json.loads(row.payload_json)
    assert len(data["runs"]) == 2
    assert [x["lesion_id"] for x in data["reconciliation"]["study"]["lesions"]] == ["AI_6", "AI_11"]


def test_ticking_none_is_recorded_as_the_scorer_taking_none(qapp, tmp_path):
    win = case_window(tmp_path)
    choose(win, set())
    assert win.run_ai_on_study() == []
    (row,) = win.store.ai_runs(win._scoring_study[0])
    assert row.proposed == ["AI_6", "AI_11"] and row.accepted == [] and segments_of(win) == [[]]


def test_no_narrowings_found_says_so_and_never_opens_the_dialog(qapp, tmp_path):
    from tests.test_suggest_app import FakeStenosis as Fake
    win = case_window(tmp_path, stenosis=Fake(found=False))
    win._choose_proposals = lambda run: (_ for _ in ()).throw(AssertionError("no dialog expected"))
    assert win.run_ai_on_study() == [] and "no narrowings" in win.statusBar().currentMessage().lower()
    assert win.store.ai_runs(win._scoring_study[0]) != []                        # the empty result is kept too


def test_a_model_failure_is_shown_and_changes_nothing(qapp, tmp_path):
    win = case_window(tmp_path, stenosis=FakeStenosis(fail=True))
    assert win.run_ai_on_study() is None
    assert win.messages and "model exploded" in win.messages[0]
    assert segments_of(win) == [[]] and win.store.ai_runs(win._scoring_study[0]) == []


def test_only_the_series_of_the_open_case_are_analysed(qapp, tmp_path):
    win = open_window(tmp_path, make_source(tmp_path))
    win.add_user("Ana", "resident")
    paths = [Path(win.item_list.item(i).data(PATH_ROLE)) for i in range(win.item_list.count())]
    other = pydicom.dcmread(paths[1])
    other.StudyInstanceUID = "1.2.3.99"                                          # a different patient's study
    other.save_as(paths[1])
    win.item_list.setCurrentRow(0)
    assert win.score_selected_case()
    win.segmenter, win.stenosis = FakeSegmenter(), FakeStenosis()
    win.messages = []
    win._warn = win.messages.append
    choose(win, set())
    win.run_ai_on_study()
    assert [r.series_instance_uid for r in win.proposed[0].runs] == [paths[0].stem]


# ---- the real dialog and the evidence jump ----
def test_the_real_dialog_returns_the_ticked_ids_and_the_jump_button_moves_the_viewer(qapp, tmp_path, monkeypatch):
    win = case_window(tmp_path)
    jumps = []
    win.show_evidence = lambda series, frame: jumps.append((series, frame)) or True

    def fake_exec(self):
        self.list.item(0).setCheckState(Qt.CheckState.Checked)
        self.list.setCurrentRow(1)
        self.show_button.click()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(ProposalDialog, "exec", fake_exec)
    assert win.run_ai_on_study() == ["AI_6"]
    assert len(jumps) == 1 and jumps[0][1] == 2                                  # AI_11's best frame is the middle one


def test_show_evidence_selects_the_series_and_shows_the_frame(qapp, tmp_path):
    win = case_window(tmp_path)
    choose(win, set())
    win.run_ai_on_study()
    series, frame = win.proposed[0].evidence_of("AI_6")
    other = next(i for i in range(win.item_list.count())
                 if Path(win.item_list.item(i).data(PATH_ROLE)).stem != series)
    win.item_list.setCurrentRow(other)
    assert win._shown_uid != series
    assert win.show_evidence(series, frame) is True
    assert win._shown_uid == series and win.cine.frame_index() == frame


def test_show_evidence_for_a_series_that_is_gone_says_so(qapp, tmp_path):
    win = case_window(tmp_path)
    assert win.show_evidence("no-such-series", 1) is False
    assert "no longer" in win.statusBar().currentMessage().lower()


def test_candidates_outside_every_segment_are_never_reported_as_no_narrowings(qapp, tmp_path, monkeypatch):
    from cagsyntax import app as app_module
    from cagsyntax.agent.schema import RawCVLesionCandidate
    real = app_module.run_study

    def unplaced_run(*args, **kwargs):
        run = real(*args, **kwargs)
        stray = RawCVLesionCandidate(candidate_id="x", stenosis_score=0.9, segment_overlap=0.0,
                                     series_instance_uid="s", sop_instance_uid="s", frame_index=0, pixels=5)
        run.reconciliation = run.reconciliation.model_copy(update={
            "study": run.reconciliation.study.model_copy(update={"lesions": []}), "unplaced": [stray],
            "warnings": ["1 candidate(s) lie outside the outlined segments and were not turned into lesions; "
                         "check them in the viewer."]})
        run.skipped = [("bad.dcm", "unreadable")]
        return run
    monkeypatch.setattr(app_module, "run_study", unplaced_run)
    win = case_window(tmp_path)
    assert win.run_ai_on_study() == []
    msg = win.statusBar().currentMessage().lower()
    assert "no narrowings found" not in msg and "outside" in msg and "bad.dcm" in msg


# ---- review follow-ups ----
def test_accepted_means_what_reached_the_form_not_only_what_was_ticked(qapp, tmp_path):
    from cagsyntax.scoring import Case, Lesion
    win = case_window(tmp_path)
    case = win.panel.case()
    win.panel.set_case(Case(dominance=case.dominance, scoring_dominance=case.scoring_dominance,
                            lesions=[Lesion(segments=["6"])], diffuse_segments=case.diffuse_segments))
    choose(win, {"AI_6", "AI_11"})
    assert win.run_ai_on_study() == ["AI_6", "AI_11"]
    (row,) = win.store.ai_runs(win._scoring_study[0])
    assert row.proposed == ["AI_6", "AI_11"] and row.accepted == ["AI_11"]       # segment 6 was already in the form


def test_the_proposal_dialog_is_deleted_after_use(qapp, tmp_path, monkeypatch):
    import shiboken6
    from PySide6.QtCore import QEvent
    win = case_window(tmp_path)
    seen = []

    def fake_exec(self):
        seen.append(self)
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(ProposalDialog, "exec", fake_exec)
    win.run_ai_on_study()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    assert seen and not shiboken6.isValid(seen[0])


def test_the_series_of_another_patient_with_the_same_study_uid_is_not_analysed(qapp, tmp_path):
    win = open_window(tmp_path, make_source(tmp_path))
    win.add_user("Ana", "resident")
    paths = [Path(win.item_list.item(i).data(PATH_ROLE)) for i in range(win.item_list.count())]
    other = pydicom.dcmread(paths[1])
    other.StudyInstanceUID = pydicom.dcmread(paths[0]).StudyInstanceUID          # same study uid ...
    other.PatientID = "someone-else"                                              # ... another patient
    other.save_as(paths[1])
    win.item_list.setCurrentRow(0)
    assert win.score_selected_case()
    win.segmenter, win.stenosis = FakeSegmenter(), FakeStenosis()
    choose(win, set())
    win.run_ai_on_study()
    assert [r.series_instance_uid for r in win.proposed[0].runs] == [paths[0].stem]


def test_the_jump_says_when_it_had_to_switch_the_folder_filter(qapp, tmp_path):
    win = case_window(tmp_path)
    series = [Path(win.item_list.item(i).data(PATH_ROLE)).stem for i in range(win.item_list.count())]
    win.library.assign([series[1]], "Elsewhere")
    win.refresh_list()
    win.folder_combo.setCurrentText("Elsewhere")                                  # hides the other series
    assert win._row_of(series[0]) is None
    assert win.show_evidence(series[0], 1) is True
    assert "all folders" in win.statusBar().currentMessage().lower()


def test_show_evidence_reopens_a_series_that_is_selected_but_not_shown(qapp, tmp_path):
    win = case_window(tmp_path)
    series = Path(win.item_list.item(0).data(PATH_ROLE)).stem
    win.item_list.setCurrentRow(0)
    win._shown_uid = None                                                         # an earlier open had failed
    assert win.show_evidence(series, 1) is True and win._shown_uid == series


def test_a_blocked_action_shows_a_dialog_not_only_a_status_bar_line(qapp, tmp_path):
    win = case_window(tmp_path)
    win.stenosis, win.stenosis_error = None, "No stenosis model installed (expected at X)."
    assert win.run_ai_on_study() is None and win.suggest_lesions() is None
    assert len(win.messages) == 2 and all("stenosis model" in m.lower() for m in win.messages)


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A blocked action now opens a dialog; in tests it must never wait for a click."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
