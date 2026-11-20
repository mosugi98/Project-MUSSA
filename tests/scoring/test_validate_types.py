"""Malformed input must never crash score_case or be scored as if it were valid."""
import pytest

from cagsyntax.scoring.engine import score_case
from cagsyntax.scoring.model import Case, Lesion
from tests.scoring.builders import case, lesion, occluded


def codes(result):
    return {i.code for i in result.issues}


def test_duplicate_diffuse_segment_is_an_error_not_double_counted():
    r = score_case(case(lesion(), diffuse=["7", "7"]))
    assert r.status == "invalid" and "duplicate_diffuse_segment" in codes(r) and r.total is None


BAD_LESIONS = [
    ("occlusion as string", dict(occlusion="yes")),
    ("occlusion as int", dict(occlusion=1)),
    ("thrombus as string no", dict(thrombus="no")),
    ("calcification as string", dict(heavy_calcification="no")),
    ("tortuosity as int", dict(severe_tortuosity=1)),
    ("segments nested list", dict(segments=[["7"]])),
    ("segments as string", dict(segments="8")),
    ("bifurcation as list", dict(bifurcation=["A"])),
    ("bifurcation as int", dict(bifurcation=3)),
    ("trifurcation as bool", dict(trifurcation=True)),
    ("trifurcation as float", dict(trifurcation=2.0)),
    ("trifurcation as string", dict(trifurcation="2")),
    ("age as list", dict(occlusion=True, first_segment="8", age_over_3_months=["x"])),
    ("first segment as list", dict(occlusion=True, first_segment=["8"])),
    ("side branch as list", dict(occlusion=True, first_segment="8", side_branch=["no"])),
    ("beyond as list", dict(occlusion=True, first_segment="2", beyond_first_visualized=["3"])),
    ("blunt stump as string", dict(occlusion=True, first_segment="8", blunt_stump="no")),
]


@pytest.mark.parametrize("name,fields", BAD_LESIONS, ids=[b[0] for b in BAD_LESIONS])
def test_wrong_typed_lesion_fields_are_invalid_and_never_raise(name, fields):
    r = score_case(case(lesion(**fields)))
    assert r.status == "invalid", (name, r.issues)
    assert r.total is None
    assert codes(r) & {"bad_type", "bad_input"}


@pytest.mark.parametrize("bad", [None, {"segments": ["8"]}, "lesion", 5])
def test_non_lesion_objects_are_invalid(bad):
    r = score_case(Case(dominance="right", scoring_dominance=None, lesions=[bad], diffuse_segments=[]))
    assert r.status == "invalid" and "bad_input" in codes(r)


def test_wrong_typed_case_fields_are_invalid():
    assert score_case(Case(dominance=["right"], scoring_dominance=None, lesions=[lesion()])).status == "invalid"
    assert score_case(Case(dominance="right", scoring_dominance=["left"], lesions=[lesion()])).status == "invalid"
    assert score_case(Case(dominance="right", scoring_dominance=None, lesions=[lesion()],
                           diffuse_segments=[["7"]])).status == "invalid"
    assert score_case(Case(dominance="right", scoring_dominance=None, lesions="x")).status == "invalid"


def test_string_no_is_never_scored_as_yes():
    # the failure the review found: thrombus="no" used to add a point
    assert score_case(case(lesion(thrombus="no"))).total is None


def test_after_a_trifurcation_bifurcation_is_not_asked_and_may_be_none():
    ok = score_case(case(lesion(trifurcation=2, bifurcation=None)))
    assert ok.status == "complete" and ok.total == 2 + 4
    both = score_case(case(lesion(trifurcation=2, bifurcation="D")))
    assert both.status == "invalid" and "trifurcation_and_bifurcation" in codes(both)


def test_group_32_5_is_intermediate_like_22_5():
    from cagsyntax.scoring.engine import group_for
    assert group_for(22.5) == group_for(32.5) == "intermediate"
