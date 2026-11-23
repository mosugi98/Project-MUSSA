import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cagsyntax.agent.reconcile import reconcile
from cagsyntax.agent.schema import RawCVLesionCandidate, RunPerceptionSummary
from cagsyntax.ui.proposal_dialog import ProposalDialog


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def cand(cid, segment, score, series="s1", frame=2):
    return RawCVLesionCandidate(candidate_id=cid, predicted_segment=segment, stenosis_score=score,
                                segment_overlap=0.9 if segment else 0.0, series_instance_uid=series,
                                sop_instance_uid="sop", frame_index=frame, bbox_xyxy=(1, 2, 30, 40), pixels=120)


def reconciliation():
    run = RunPerceptionSummary(series_instance_uid="s1", sop_instance_uid="sop", study_instance_uid="st",
                               view_label="LAO 30 CRAN 20", frame_count=5, analysed_frames=[2],
                               candidates=[cand("a", "6", 0.91), cand("b", "9", 0.95), cand("c", None, 0.7)])
    return reconcile([run])


@pytest.fixture
def dialog(qapp):
    shown = []
    d = ProposalDialog(reconciliation(), on_show=shown.append)
    d.shown = shown
    yield d
    d.close()


def test_it_says_these_are_proposals_and_nothing_is_added_until_pressed(dialog):
    text = dialog.notice_label.text().lower()
    assert "ai proposal" in text and "not a diagnosis" in text and "tick" in text and "dominance" in text


def test_every_proposed_lesion_is_listed_unticked_with_its_segment_view_and_score(dialog):
    assert dialog.list.count() == 2
    first = dialog.list.item(0)                                     # segment 6 comes first in table order
    assert "segment 6" in first.text() and "LAO 30 CRAN 20" in first.text() and "91%" in first.text()
    assert first.checkState() == Qt.CheckState.Unchecked and dialog.chosen() == []


def test_a_lesion_that_needs_attention_says_why(dialog):
    texts = [dialog.list.item(i).text() for i in range(dialog.list.count())]
    flagged = next(t for t in texts if "segment 6" in t)            # segment 6 is a busy bifurcation area
    assert "check" in flagged.lower() and "bifurcation" in flagged.lower()
    calm = next(t for t in texts if "segment 9" in t)
    assert "check" not in calm.lower()


def test_ticking_chooses_lesions_in_proposed_order(dialog):
    for row in (1, 0):
        dialog.list.item(row).setCheckState(Qt.CheckState.Checked)
    assert dialog.chosen() == ["AI_6", "AI_9"]
    assert "2" in dialog.add_button.text()


def test_show_in_viewer_reports_the_selected_lesion_and_needs_a_selection(dialog):
    assert not dialog.show_button.isEnabled()
    dialog.list.setCurrentRow(1)
    assert dialog.show_button.isEnabled()
    dialog.show_button.click()
    assert dialog.shown == ["AI_9"]


def test_candidates_outside_every_segment_are_reported_but_are_not_addable_rows(dialog):
    info = dialog.info_label.text().lower()
    assert "outside" in info and "1" in info
    assert dialog.list.count() == 2


def test_nothing_proposed_leaves_nothing_to_tick(qapp):
    run = RunPerceptionSummary(series_instance_uid="s1", sop_instance_uid="sop", study_instance_uid="st",
                               view_label="x", frame_count=1)
    d = ProposalDialog(reconcile([run]), on_show=lambda _id: None)
    assert d.list.count() == 0 and d.chosen() == [] and not d.show_button.isEnabled()
    assert "no narrowings" in d.info_label.text().lower()
    d.close()
