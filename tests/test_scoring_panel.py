import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import dataclasses

import pytest
from PySide6.QtWidgets import QApplication

from cagsyntax.scoring import Case, Lesion
from cagsyntax.ui.scoring_panel import ScoringPanel
from tests.scoring.builders import case, lesion, occluded


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(qapp):
    return ScoringPanel()


PLAIN = [("occlusion", False), ("trifurcation", 0), ("bifurcation", "none"), ("severe_tortuosity", False),
         ("length_gt20", False), ("heavy_calcification", False), ("thrombus", False)]


def fill_plain(p):
    for field, value in PLAIN:
        assert p.answer(field, value)


def test_plain_lesion_shows_total_and_group(panel):
    panel.set_dominance("right")
    panel.toggle_segment("6")
    fill_plain(panel)
    assert panel.answer("aorto_ostial", False)
    r = panel.result()
    assert (r.status, r.total, r.group) == ("complete", 7.0, "low")
    text = panel.result_label.text()
    assert "Total score 7" in text and "low" in text


def test_unanswered_questions_show_incomplete_with_each_missing_question_and_no_total(panel):
    panel.set_dominance("right")
    panel.toggle_segment("8")
    r = panel.result()
    assert r.status == "incomplete" and r.total is None
    text = panel.result_label.text()
    assert "Incomplete" in text and "total occlusion" in text and "trifurcation" in text
    assert "Total score" not in text


def test_no_dominance_chosen_yet_is_incomplete_and_segments_cannot_be_picked(panel):
    panel.toggle_segment("8")
    assert panel.case().lesions[0].segments == []
    assert "dominance" in panel.result_label.text().lower()


def test_changing_the_side_branch_clears_stale_trifurcation_and_bifurcation(panel):  # Review Focus 4
    panel.set_dominance("right")
    for seg in ("2", "3"):
        panel.toggle_segment(seg)
    for field, value in [("occlusion", True), ("first_segment", "2"), ("age_over_3_months", "yes"),
                         ("blunt_stump", False), ("bridging", False), ("beyond_first_visualized", "none"),
                         ("side_branch", "large"), ("trifurcation", 0), ("bifurcation", "D"),
                         ("bifurcation_angle_lt70", True)]:
        assert panel.answer(field, value), field
    assert panel.is_enabled("trifurcation") and panel.is_enabled("bifurcation_angle_lt70")
    assert panel.answer("side_branch", "small")
    assert not panel.is_enabled("trifurcation") and not panel.is_enabled("bifurcation")
    les = panel.case().lesions[0]
    assert (les.trifurcation, les.bifurcation, les.bifurcation_angle_lt70) == (None, None, None)
    assert not any("not_asked" in i.code or "without_occlusion" in i.code for i in panel.result().issues)


def test_switching_occlusion_off_clears_occlusion_answers(panel):
    panel.set_dominance("right")
    panel.toggle_segment("2")
    panel.answer("occlusion", True)
    panel.answer("first_segment", "2")
    panel.answer("occlusion", False)
    les = panel.case().lesions[0]
    assert les.first_segment is None and les.side_branch is None
    assert panel.is_enabled("length_gt20") and not panel.is_enabled("first_segment")


def test_answers_for_questions_that_do_not_apply_are_ignored(panel):
    panel.set_dominance("right")
    panel.toggle_segment("8")
    panel.answer("occlusion", False)
    assert panel.answer("side_branch", "large") is False
    assert panel.case().lesions[0].side_branch is None


def test_dominance_change_drops_segments_reports_them_and_says_so_in_the_result(panel):
    panel.set_dominance("right")
    for seg in ("3", "4", "16"):
        panel.toggle_segment(seg)
    removed = panel.set_dominance("left")
    assert removed == ["4", "16"]
    assert panel.case().lesions[0].segments == ["3"]
    text = panel.result_label.text()
    assert "removed" in text.lower() and "4" in text and "16" in text


def test_codominant_needs_a_scoring_table_and_then_scores_with_it(panel):
    panel.set_dominance("co-dominant")
    assert panel.scoring_combo.isEnabled()
    panel.toggle_segment("5")                     # no scoring table yet: nothing can be picked
    assert panel.case().lesions[0].segments == []
    assert "scoring table" in panel.result_label.text().lower()
    panel.set_dominance("co-dominant", "left")
    panel.toggle_segment("5")
    fill_plain(panel)
    panel.answer("aorto_ostial", False)
    r = panel.result()
    assert r.status == "complete" and r.total == 12.0 and r.scoring_dominance == "left"
    panel.set_dominance("right")
    assert not panel.scoring_combo.isEnabled()


def test_lesions_can_be_added_up_to_twelve_and_removed(panel):
    for _ in range(20):
        panel.add_lesion()
    assert len(panel.case().lesions) == 12
    panel.remove_lesion(0)
    assert len(panel.case().lesions) == 11 and panel.current_lesion() < 11
    for _ in range(11):
        panel.remove_lesion(0)
    assert panel.case().lesions == [] and panel.result().status == "incomplete"


def test_ostial_question_follows_the_selected_segments(panel):
    panel.set_dominance("right")
    panel.toggle_segment("8")
    assert not panel.is_enabled("aorto_ostial")
    panel.toggle_segment("6")
    assert panel.is_enabled("aorto_ostial")


def test_diffuse_segments_add_one_point_each(panel):
    panel.set_dominance("right")
    panel.toggle_segment("8")
    fill_plain(panel)
    panel.toggle_diffuse("7")
    panel.toggle_diffuse("8")
    assert panel.result().total == 2.0 + 2
    panel.toggle_diffuse("15")                    # does not exist under right dominance
    assert panel.case().diffuse_segments == ["7", "8"]


def test_set_case_round_trip_and_live_changed_signal(panel):
    c = case(lesion(segments=["7"]), occluded(side_branch="large", trifurcation=0, bifurcation="none"))
    seen = []
    panel.changed.connect(lambda: seen.append(1))
    panel.set_case(c)
    assert panel.case() == c and seen
    assert len(panel.case().lesions) == 2


def test_clicking_an_answer_button_sets_the_answer(panel):
    panel.set_dominance("right")
    panel.toggle_segment("8")
    panel.option_button("thrombus", True).click()
    assert panel.case().lesions[0].thrombus is True
    panel.option_button("thrombus", False).click()
    assert panel.case().lesions[0].thrombus is False


def test_disclaimer_is_always_visible(panel):
    assert "not a certified medical device" in panel.disclaimer_label.text().lower()
    assert not panel.disclaimer_label.isHidden()


def test_set_case_prunes_segments_that_do_not_exist_for_the_dominance(panel):
    panel.set_case(case(lesion(segments=["15"]), diffuse=["15"]))
    assert panel.case().lesions[0].segments == [] and panel.case().diffuse_segments == []
    assert "15" in panel.result_label.text()


def test_set_case_with_an_unknown_first_segment_does_not_raise(panel):
    odd = Case(dominance="right", scoring_dominance=None,
               lesions=[Lesion(segments=["99"], occlusion=True, first_segment="99")], diffuse_segments=[])
    panel.set_case(odd)
    assert panel.case().lesions[0].segments == []


def test_removing_a_lesion_before_the_current_one_keeps_the_same_lesion_selected(panel):
    panel.set_dominance("right")
    panel.toggle_segment("6")
    panel.add_lesion()
    panel.toggle_segment("7")
    panel.add_lesion()
    panel.toggle_segment("8")
    assert panel.current_lesion() == 2
    panel.remove_lesion(0)
    assert panel.current_lesion() == 1
    assert panel.case().lesions[panel.current_lesion()].segments == ["8"]
