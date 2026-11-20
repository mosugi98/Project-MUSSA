from cagsyntax.scoring.model import Case, Lesion
from cagsyntax.scoring.validate import validate


def lesion(**kw):
    """A fully answered, valid non-occlusive lesion on segment 8 unless overridden."""
    base = dict(segments=["8"], occlusion=False, trifurcation=0, bifurcation="none",
                severe_tortuosity=False, length_gt20=False, heavy_calcification=False,
                thrombus=False)
    base.update(kw)
    return Lesion(**base)


def occluded(**kw):
    base = dict(segments=["2", "3"], occlusion=True, first_segment="2", age_over_3_months="yes",
                blunt_stump=False, bridging=False, beyond_first_visualized="none",
                side_branch="no", length_gt20=None, trifurcation=None, bifurcation=None)
    base.update(kw)
    return lesion(**base)


def case(*lesions, dominance="right", scoring=None, diffuse=()):
    return Case(dominance=dominance, scoring_dominance=scoring, lesions=list(lesions),
                diffuse_segments=list(diffuse))


def codes(case_):
    errors, missing = validate(case_)
    return {i.code for i in errors}, {i.code for i in missing}


def test_valid_complete_case_has_no_issues():
    assert codes(case(lesion(), occluded())) == (set(), set())


def test_no_dominance_is_missing():
    assert codes(case(lesion(), dominance=None)) == (set(), {"no_dominance"})


def test_codominant_without_scoring_table_is_missing():  # Review Focus 4
    assert "no_scoring_dominance" in codes(case(lesion(), dominance="co-dominant"))[1]


def test_codominant_with_scoring_table_is_fine():
    assert codes(case(lesion(), dominance="co-dominant", scoring="left")) == (set(), set())


def test_scoring_dominance_must_match_right_or_left():
    assert "dominance_mismatch" in codes(case(lesion(), dominance="right", scoring="left"))[0]


def test_zero_lesions_is_missing_not_zero():  # Review Focus 1
    assert codes(case()) == (set(), {"no_lesions"})


def test_lesion_without_segments_is_missing():  # Review Focus 2
    assert "no_segments" in codes(case(lesion(segments=[])))[1]


def test_segment_not_applicable_to_dominance_is_an_error():  # Review Focus 3
    assert "segment_not_applicable" in codes(case(lesion(segments=["15"])))[0]
    assert "segment_not_applicable" in codes(case(lesion(segments=["4"]), dominance="left"))[0]


def test_unknown_and_duplicate_segments():
    assert "unknown_segment" in codes(case(lesion(segments=["99"])))[0]
    assert "duplicate_segment" in codes(case(lesion(segments=["8", "8"])))[0]


def test_thirteen_lesions_is_an_error():  # Review Focus 5
    assert "too_many_lesions" in codes(case(*[lesion() for _ in range(13)]))[0]
    assert "too_many_lesions" not in codes(case(*[lesion() for _ in range(12)]))[0]


def test_first_segment_must_be_in_lesion():
    assert "first_segment_not_in_lesion" in codes(case(occluded(first_segment="8")))[0]


def test_occlusion_fields_without_occlusion_is_an_error():
    assert "occlusion_fields_without_occlusion" in codes(case(lesion(blunt_stump=True)))[0]
    assert "occlusion_fields_without_occlusion" in codes(case(lesion(first_segment="8")))[0]


def test_incomplete_occlusion_answers_are_missing():
    assert "occlusion_incomplete" in codes(case(occluded(first_segment=None)))[1]
    assert "occlusion_incomplete" in codes(case(occluded(bridging=None)))[1]
    assert "occlusion_incomplete" in codes(case(occluded(beyond_first_visualized=None)))[1]


def test_length_with_occlusion_is_an_error():
    assert "length_with_occlusion" in codes(case(occluded(length_gt20=True)))[0]


def test_trifurcation_and_bifurcation_are_exclusive():
    assert "trifurcation_and_bifurcation" in codes(case(lesion(trifurcation=2, bifurcation="B")))[0]


def test_angle_needs_a_bifurcation_and_letter_needs_an_angle_answer():
    assert "angle_without_bifurcation" in codes(case(lesion(bifurcation_angle_lt70=True)))[0]
    assert "question_unanswered" in codes(case(lesion(bifurcation="B")))[1]
    assert codes(case(lesion(bifurcation="B", bifurcation_angle_lt70=False))) == (set(), set())


def test_ostial_only_applicable_for_segments_1_5_6_11():
    assert "ostial_not_applicable" in codes(case(lesion(aorto_ostial=True)))[0]
    assert "question_unanswered" in codes(case(lesion(segments=["6"])))[1]
    assert codes(case(lesion(segments=["6"], aorto_ostial=True))) == (set(), set())


def test_unanswered_questions_are_missing():
    for field in ("trifurcation", "bifurcation", "severe_tortuosity", "heavy_calcification",
                  "thrombus", "length_gt20", "occlusion"):
        assert "question_unanswered" in codes(case(lesion(**{field: None})))[1], field


def test_diffuse_segments_must_apply_to_dominance():
    assert "diffuse_segment_not_applicable" in codes(case(lesion(), diffuse=["15"]))[0]
    assert "diffuse_segment_not_applicable" in codes(case(lesion(), diffuse=["99"]))[0]


def test_beyond_segment_must_be_allowed_for_the_occlusions_main_segment():
    # TO main segment 2, right: allowed range is 2,3,4,16 (and "none")
    assert codes(case(occluded(beyond_first_visualized="3"))) == (set(), set())
    assert "beyond_segment_invalid" in codes(case(occluded(beyond_first_visualized="7")))[0]
    # main segment 5 denies 9, 9a, 10, 10a, 12, 12a, 12b, 14a, 14b
    assert "beyond_segment_invalid" in codes(case(occluded(segments=["5"], first_segment="5", beyond_first_visualized="9")))[0]


def test_trifurcation_and_bifurcation_not_asked_after_small_side_branch():
    for side in ("no", "small"):
        assert "trifurcation_bifurcation_not_asked" in codes(case(occluded(side_branch=side, trifurcation=0)))[0]
        assert "trifurcation_bifurcation_not_asked" in codes(case(occluded(side_branch=side, bifurcation="none")))[0]
        assert codes(case(occluded(side_branch=side))) == (set(), set())


def test_trifurcation_and_bifurcation_asked_after_large_side_branch():
    for side in ("large", "both"):
        assert "question_unanswered" in codes(case(occluded(side_branch=side)))[1]
        assert codes(case(occluded(side_branch=side, trifurcation=0, bifurcation="none"))) == (set(), set())


def test_beyond_question_not_asked_when_main_segment_has_a_single_candidate():
    # main segment 8 has only itself in range: the official form skips the question
    skipped = occluded(segments=["8"], first_segment="8", beyond_first_visualized=None)
    assert codes(case(skipped)) == (set(), set())
    assert "beyond_not_asked" in codes(case(occluded(segments=["8"], first_segment="8", beyond_first_visualized="none")))[0]
    # main segment 3 under left dominance: 4 and 16 are hidden, so only segment 3 remains
    assert codes(case(occluded(segments=["3"], first_segment="3", beyond_first_visualized=None), dominance="left")) == (set(), set())


def test_malformed_input_does_not_raise():
    bad = Case(dominance="right", scoring_dominance=None, lesions=[Lesion(segments="8")], diffuse_segments="7")
    validate(bad)
