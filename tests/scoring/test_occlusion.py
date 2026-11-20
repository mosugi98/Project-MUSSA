import pytest

from cagsyntax.scoring.engine import score_case, visualized_points
from tests.scoring.builders import case, lesion, occluded


def total(*lesions, **kw):
    r = score_case(case(*lesions, **kw))
    assert r.status == "complete", r.issues
    return r.total


# ---- first segment x5, others x2 ----
def test_first_segment_x5_other_segments_x2():
    # segments 2 (weight 1, first, x5) and 3 (weight 1, x2); beyond "3" scores 0
    assert total(occluded(beyond_first_visualized="3")) == 5 + 2


def test_only_the_marked_first_segment_is_x5():
    assert total(occluded(first_segment="3", beyond_first_visualized="4")) == 2 + 5


def test_left_main_occlusion_by_dominance():
    les = occluded(segments=["5"], first_segment="5", aorto_ostial=False)
    assert total(les, dominance="left") == 6 * 5 + 4   # beyond "none", main 5, left = 4
    assert total(les, dominance="right") == 5 * 5 + 3  # right = 3


# ---- sub-scores ----
@pytest.mark.parametrize("age,pts", [("no", 0), ("yes", 1), ("unknown", 1)])
def test_age_of_occlusion(age, pts):
    assert total(occluded(age_over_3_months=age, beyond_first_visualized="3")) == 7 + pts


def test_blunt_stump_and_bridging_one_point_each():
    assert total(occluded(blunt_stump=True, beyond_first_visualized="3")) == 7 + 1
    assert total(occluded(bridging=True, beyond_first_visualized="3")) == 7 + 1


@pytest.mark.parametrize("side,pts", [("no", 0), ("small", 1), ("large", 1), ("both", 1)])
def test_side_branch_at_origin(side, pts):
    asked = {"trifurcation": 0, "bifurcation": "none"} if side in ("large", "both") else {}
    assert total(occluded(side_branch=side, beyond_first_visualized="3", **asked)) == 7 + pts


def test_all_occlusion_points_together():
    les = occluded(age_over_3_months="yes", blunt_stump=True, bridging=True, side_branch="large",
                   beyond_first_visualized="none", trifurcation=0, bifurcation="none")
    assert total(les) == 7 + 1 + 1 + 1 + 1 + 2


def test_occlusion_still_scores_bifurcation_and_other_features():
    les = occluded(beyond_first_visualized="3", side_branch="large", trifurcation=0, bifurcation="C",
                   bifurcation_angle_lt70=False, heavy_calcification=True)
    assert total(les) == 7 + 1 + 1 + 2


def test_non_occluded_lesion_ignores_occlusion_answers():
    assert total(lesion(segments=["2", "3"])) == (1 + 1) * 2


def test_parts_sum_and_label_the_occlusion_scores():
    r = score_case(case(occluded(age_over_3_months="yes", beyond_first_visualized="3")))
    lr = r.lesions[0]
    assert sum(p.points for p in lr.parts) == lr.total == 8
    labels = " ".join(p.label for p in lr.parts)
    assert "occlusion" in labels.lower() and "age" in labels.lower()


# ---- beyond-occlusion rule, ported from the official code (hand-traced) ----
@pytest.mark.parametrize("dom,main,active,expected", [
    ("right", "2", "none", 2),   # none with segment 2 right-dominant special case
    ("right", "2", "3", 0),
    ("right", "2", "4", 1),      # official special case (active 4, number 2) -> 1 (frameset.js:1745)
    ("right", "1", "none", 3),
    ("left", "1", "none", 1),
    ("right", "3", "none", 1),
    ("right", "4", "none", 0),   # segments 4 and 16 are denied for main segment 4
    ("right", "6", "none", 2),
    ("right", "6", "8", 1),
    ("right", "5", "none", 3),
    ("left", "5", "none", 4),
    ("right", "5", "7", 1),
    ("right", "5", "8", 2),
    ("right", "5", "13", 1),
    ("right", "5", "14", 2),
    ("left", "5", "15", 3),
    ("left", "5", "7", 1),
])
def test_visualized_points_matches_official_trace(dom, main, active, expected):
    assert visualized_points(dom, main, active) == expected


def test_beyond_question_skipped_scores_zero():
    les = occluded(segments=["8"], first_segment="8", beyond_first_visualized=None)
    r = score_case(case(les))
    assert r.status == "complete" and r.total == 1 * 5
