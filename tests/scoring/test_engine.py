import pytest

from cagsyntax.scoring.engine import group_for, score_case
from tests.scoring.builders import case, lesion


def total(*lesions, **kw):
    r = score_case(case(*lesions, **kw))
    assert r.status == "complete", r.issues
    return r.total


def test_lad_proximal_right_is_weight_times_two():
    assert total(lesion(segments=["6"], aorto_ostial=False)) == 7.0


def test_left_main_by_dominance():
    assert total(lesion(segments=["5"], aorto_ostial=False)) == 10.0
    assert total(lesion(segments=["5"], aorto_ostial=False), dominance="left") == 12.0


def test_rca_has_zero_weight_under_left_dominance():
    assert total(lesion(segments=["2"]), dominance="left") == 0.0


def test_bifurcation_medina_d_with_angle_left_dominant_lm_plus_lad():
    les = lesion(segments=["5", "6"], aorto_ostial=False, bifurcation="D", bifurcation_angle_lt70=True)
    assert total(les, dominance="left") == (6 + 3.5) * 2 + 2 + 1


@pytest.mark.parametrize("letter,pts", [("A", 1), ("B", 1), ("C", 1), ("D", 2), ("E", 2), ("F", 2), ("G", 2)])
def test_bifurcation_points_by_medina_letter(letter, pts):
    assert total(lesion(bifurcation=letter, bifurcation_angle_lt70=False)) == 2 + pts


def test_angle_under_70_adds_one_only_with_a_bifurcation():
    assert total(lesion(bifurcation="A", bifurcation_angle_lt70=True)) == 2 + 1 + 1


@pytest.mark.parametrize("n,pts", [(1, 3), (2, 4), (3, 5), (4, 6)])
def test_trifurcation_points_are_n_plus_two(n, pts):
    assert total(lesion(trifurcation=n)) == 2 + pts


def test_feature_points():
    assert total(lesion(severe_tortuosity=True)) == 2 + 2
    assert total(lesion(heavy_calcification=True)) == 2 + 2
    assert total(lesion(thrombus=True)) == 2 + 1
    assert total(lesion(length_gt20=True)) == 2 + 1
    assert total(lesion(segments=["6"], aorto_ostial=True)) == 7 + 1


def test_diffuse_disease_counts_once_per_segment_for_the_whole_case():
    r = score_case(case(lesion(), diffuse=["7", "8"]))
    assert r.diffuse_points == 2 and r.total == 2 + 2
    assert [lr.total for lr in r.lesions] == [2.0]  # diffuse is not part of any lesion


def test_total_is_sum_of_lesions():
    assert total(lesion(segments=["6"], aorto_ostial=False), lesion()) == 7 + 2


def test_codominant_uses_the_chosen_scoring_table_and_reports_both():
    r = score_case(case(lesion(segments=["5"], aorto_ostial=False), dominance="co-dominant", scoring="left"))
    assert r.total == 12.0
    assert (r.dominance, r.scoring_dominance) == ("co-dominant", "left")


def test_parts_sum_to_lesion_total_and_are_labelled():
    r = score_case(case(lesion(segments=["8"], trifurcation=2, severe_tortuosity=True)))
    lr = r.lesions[0]
    assert sum(p.points for p in lr.parts) == lr.total == 2 + 4 + 2
    assert all(p.label for p in lr.parts)


def test_incomplete_case_has_no_total_group_or_lesion_results():
    r = score_case(case())
    assert r.status == "incomplete" and r.total is None and r.group is None and r.lesions == []
    assert [i.code for i in r.issues] == ["no_lesions"]


def test_invalid_case_has_no_total():
    r = score_case(case(lesion(segments=["15"])))
    assert r.status == "invalid" and r.total is None
    assert any(i.code == "segment_not_applicable" for i in r.issues)


def test_invalid_takes_precedence_over_incomplete():
    r = score_case(case(lesion(segments=["15"], thrombus=None)))
    assert r.status == "invalid"


@pytest.mark.parametrize("value,expected", [
    (0, "low"), (22, "low"), (22.5, "intermediate"), (23, "intermediate"),
    (32, "intermediate"), (32.5, "intermediate"), (33, "high"), (60, "high")])
def test_group_boundaries(value, expected):
    assert group_for(value) == expected


def test_result_carries_group():
    assert score_case(case(lesion())).group == "low"
