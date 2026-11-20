import dataclasses

import pytest

from cagsyntax.form_state import (applicable_questions, case_from_json, case_to_json, change_dominance,
                                  clean_lesion, removed_segments)
from cagsyntax.scoring import Lesion
from cagsyntax.scoring.validate import validate
from tests.scoring.builders import case, lesion, occluded

ALWAYS = {"occlusion", "severe_tortuosity", "heavy_calcification", "thrombus"}


def q(les, dom="right"):
    return applicable_questions(les, dom)


def test_plain_lesion_asks_the_always_questions_plus_length_trifurcation_bifurcation():
    assert q(lesion()) == ALWAYS | {"length_gt20", "trifurcation", "bifurcation"}


def test_unanswered_occlusion_asks_no_length_or_occlusion_details():
    assert q(Lesion(segments=["8"])) == ALWAYS | {"trifurcation", "bifurcation"}


def test_occlusion_questions_appear_only_for_an_occlusion():
    qs = q(occluded())
    assert {"first_segment", "age_over_3_months", "blunt_stump", "bridging", "side_branch"} <= qs
    assert "length_gt20" not in qs
    assert not ({"first_segment", "side_branch", "blunt_stump"} & q(lesion()))


def test_small_side_branch_removes_trifurcation_and_bifurcation_large_keeps_them():
    assert not ({"trifurcation", "bifurcation", "bifurcation_angle_lt70"} & q(occluded(side_branch="small")))
    assert {"trifurcation", "bifurcation"} <= q(occluded(side_branch="large"))
    assert {"trifurcation", "bifurcation"} <= q(occluded(side_branch="both"))


def test_occlusion_with_unanswered_side_branch_does_not_yet_ask_trifurcation():
    assert not ({"trifurcation", "bifurcation"} & q(occluded(side_branch=None)))


def test_trifurcation_yes_removes_bifurcation_and_angle_follows_a_medina_letter():
    assert "bifurcation" not in q(lesion(trifurcation=2))
    assert "bifurcation_angle_lt70" not in q(lesion(bifurcation="none"))
    assert "bifurcation_angle_lt70" in q(lesion(bifurcation="D"))


def test_ostial_only_with_segment_1_5_6_or_11_and_length_only_without_occlusion():
    assert "aorto_ostial" not in q(lesion(segments=["8"]))
    assert "aorto_ostial" in q(lesion(segments=["8", "6"]))
    assert "length_gt20" in q(lesion()) and "length_gt20" not in q(occluded())


def test_beyond_question_follows_the_main_segment():
    assert "beyond_first_visualized" in q(occluded(first_segment="2"))
    assert "beyond_first_visualized" not in q(occluded(segments=["8"], first_segment="8"))
    assert "beyond_first_visualized" not in q(occluded(first_segment=None))
    assert "beyond_first_visualized" not in q(occluded(first_segment="2"), dom=None)


# ---- Review Focus 4: stale answers ----
def test_switching_occlusion_off_clears_every_occlusion_answer():
    les = occluded(beyond_first_visualized="3", blunt_stump=True)
    les.occlusion = False
    c = clean_lesion(les, "right")
    assert (c.first_segment, c.age_over_3_months, c.blunt_stump, c.bridging,
            c.beyond_first_visualized, c.side_branch) == (None,) * 6


def test_changing_side_branch_to_small_clears_trifurcation_bifurcation_and_angle():
    les = occluded(side_branch="large", trifurcation=0, bifurcation="D", bifurcation_angle_lt70=True)
    les.side_branch = "small"
    c = clean_lesion(les, "right")
    assert (c.trifurcation, c.bifurcation, c.bifurcation_angle_lt70) == (None, None, None)
    errors, _ = validate(case(c))
    assert not errors


def test_removing_the_first_segment_from_the_lesion_clears_it_and_the_beyond_answer():
    les = occluded(beyond_first_visualized="3")
    les.segments = ["3"]
    c = clean_lesion(les, "right")
    assert c.first_segment is None and c.beyond_first_visualized is None


def test_trifurcation_yes_clears_bifurcation_and_none_clears_the_angle():
    c = clean_lesion(lesion(trifurcation=3, bifurcation="B", bifurcation_angle_lt70=False), "right")
    assert c.bifurcation is None and c.bifurcation_angle_lt70 is None
    c2 = clean_lesion(lesion(bifurcation="none", bifurcation_angle_lt70=True), "right")
    assert c2.bifurcation_angle_lt70 is None


def test_ostial_answer_cleared_when_the_ostial_segment_is_removed():
    les = lesion(segments=["8"], aorto_ostial=True)
    assert clean_lesion(les, "right").aorto_ostial is None


def test_answers_that_still_apply_are_untouched_and_input_is_not_mutated():
    les = occluded(side_branch="large", trifurcation=0, bifurcation="C", bifurcation_angle_lt70=False,
                   beyond_first_visualized="3", thrombus=True)
    before = dataclasses.asdict(les)
    c = clean_lesion(les, "right")
    assert dataclasses.asdict(c) == before
    assert dataclasses.asdict(les) == before
    assert c is not les


def test_beyond_answer_no_longer_offered_is_cleared_when_dominance_changes():
    les = occluded(segments=["3"], first_segment="3", beyond_first_visualized="4")
    c = clean_lesion(les, "left")   # under left dominance 4 and 16 do not exist
    assert c.beyond_first_visualized is None


# ---- dominance changes ----
def test_right_to_left_removes_segments_4_and_16_everywhere_and_lists_them():
    before = case(lesion(segments=["3", "4", "16"]), lesion(segments=["8"]), diffuse=["4", "7"])
    after = change_dominance(before, "left", None)
    assert after.lesions[0].segments == ["3"] and after.diffuse_segments == ["7"]
    assert after.dominance == "left" and after.scoring_dominance is None
    assert removed_segments(before, after) == ["4", "16"]


def test_left_to_right_removes_segment_15():
    before = case(lesion(segments=["8", "15"]), dominance="left")
    after = change_dominance(before, "right", None)
    assert after.lesions[0].segments == ["8"] and removed_segments(before, after) == ["15"]


def test_codominant_without_scoring_table_keeps_all_segments_and_with_one_prunes():
    before = case(lesion(segments=["4", "15"]), dominance="co-dominant", scoring="left")
    kept = change_dominance(case(lesion(segments=["4", "8"])), "co-dominant", None)
    assert kept.lesions[0].segments == ["4", "8"] and removed_segments(case(lesion(segments=["4", "8"])), kept) == []
    pruned = change_dominance(kept, "co-dominant", "left")
    assert pruned.lesions[0].segments == ["8"] and pruned.scoring_dominance == "left"
    assert removed_segments(before, change_dominance(before, "co-dominant", "right")) == ["15"]


def test_scoring_table_is_dropped_for_right_or_left_dominance():
    assert change_dominance(case(lesion()), "right", "left").scoring_dominance is None


def test_change_dominance_does_not_mutate_the_original():
    original = case(lesion(segments=["4"]))
    change_dominance(original, "left", None)
    assert original.lesions[0].segments == ["4"] and original.dominance == "right"


# ---- JSON ----
def test_json_round_trip():
    c = case(lesion(segments=["5", "6"], bifurcation="D", bifurcation_angle_lt70=True, aorto_ostial=False),
             occluded(), diffuse=["7"], dominance="co-dominant", scoring="left")
    assert case_from_json(case_to_json(c)) == c


@pytest.mark.parametrize("text", ["{", "[]", '{"dominance": "right"}', "null", '{"dominance":"right","scoring_dominance":null,"lesions":[{"bad":1}]}'])
def test_malformed_json_raises_value_error(text):
    with pytest.raises(ValueError):
        case_from_json(text)
