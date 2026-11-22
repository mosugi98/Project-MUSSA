import dataclasses

import pytest
from pydantic import ValidationError

from cagsyntax.ai.suggest import Suggestion
from cagsyntax.contract.adapters import (case_to_form, finding_from_suggestion, form_to_case, form_to_lesion,
                                         lesion_to_form, proposals_from_findings, score_to_summary)
from cagsyntax.contract.models import CaseForm, LesionForm, ModelRef
from cagsyntax.scoring import VERSION, Case, Lesion, score_case
from tests.scoring.builders import case, lesion, occluded

MODELS = [ModelRef(name="segments", identity="2026-11-21 ab12cd34"), ModelRef(name="stenosis", identity="2026-11-21 ee00ff11")]


def lesions():
    return [lesion(), lesion(segments=["6", "7"], heavy_calcification=True, length_gt20=True),
            occluded(side_branch="large", trifurcation=0, bifurcation="none"), occluded(),
            lesion(segments=["11"], bifurcation="A", bifurcation_angle_lt70=True, trifurcation=2),
            Lesion(segments=[])]                                                   # an empty draft lesion


# ---- forms <-> engine dataclasses ----
@pytest.mark.parametrize("original", lesions())
def test_a_lesion_survives_the_trip_through_the_contract_unchanged(original):
    form = lesion_to_form(original)
    assert isinstance(form, LesionForm) and form_to_lesion(form) == original


def test_the_form_carries_every_field_of_the_engines_lesion():
    assert set(LesionForm.model_fields) == {f.name for f in dataclasses.fields(Lesion)}


def test_the_result_does_not_share_lists_with_the_form():
    form = lesion_to_form(lesion(segments=["6"]))
    back = form_to_lesion(form)
    back.segments.append("7")
    assert form.segments == ["6"]


def test_a_whole_case_survives_the_trip_with_dominance_and_diffuse_segments():
    original = case(lesion(), lesion(segments=["11"]), dominance="co-dominant", scoring="left", diffuse=["8", "9"])
    form = case_to_form(original)
    assert isinstance(form, CaseForm) and form.diffuse_segments == ["8", "9"]
    assert form_to_case(form) == original


def test_scoring_before_and_after_the_trip_is_identical():
    for les in lesions()[:5]:
        original = case(les)
        after = form_to_case(CaseForm.model_validate_json(case_to_form(original).model_dump_json()))
        a, b = score_case(original), score_case(after)
        assert (a.status, a.total, a.group, [i.code for i in a.issues]) == (b.status, b.total, b.group, [i.code for i in b.issues])


def test_a_case_with_a_value_the_contract_does_not_know_is_refused_not_passed_on():
    bad = case(lesion(bifurcation="Z"))
    with pytest.raises(ValidationError):
        case_to_form(bad)


def test_an_incomplete_draft_case_is_fine():
    draft = Case(dominance=None, scoring_dominance=None, lesions=[Lesion(segments=[])])
    assert form_to_case(case_to_form(draft)) == draft


# ---- the engine's answer as a read-only snapshot ----
def test_a_complete_result_becomes_a_summary_with_the_engine_version():
    result = score_case(case(lesion()))
    summary = score_to_summary(result)
    assert summary.status == "complete" and summary.total == result.total == 2.0 and summary.group == "low"
    assert summary.engine_version == VERSION and summary.issues == []
    assert summary.lesion_totals == [r.total for r in result.lesions] and summary.diffuse_points == result.diffuse_points


def test_an_incomplete_result_keeps_its_issues_with_their_lesion_index():
    result = score_case(Case(dominance="right", scoring_dominance=None, lesions=[Lesion(segments=["6"])]))
    summary = score_to_summary(result)
    assert summary.status == "incomplete" and summary.total is None and summary.issues
    assert [(i.code, i.lesion) for i in summary.issues] == [(i.code, i.lesion) for i in result.issues]


# ---- suggestions -> findings -> proposals ----
def suggestion(segment="6", score=0.9, pixels=120, overlap=0.8, box=(5, 6, 20, 30)):
    return Suggestion(segment, score, pixels, overlap, box)


def finding(s=None, frame=2):
    return finding_from_suggestion(s or suggestion(), series_uid="2.25.1", frame=frame, primary_angle=30.0,
                                   secondary_angle=-20.0, models=MODELS)


def test_a_suggestion_becomes_a_finding_with_its_evidence_and_models():
    f = finding()
    assert (f.segment, f.score, f.pixels, f.overlap) == ("6", 0.9, 120, 0.8)
    e = f.evidence
    assert (e.series_uid, e.frame, e.primary_angle, e.secondary_angle, e.box) == ("2.25.1", 2, 30.0, -20.0, (5, 6, 20, 30))
    assert [m.name for m in f.models] == ["segments", "stenosis"]


def test_an_unplaced_suggestion_becomes_an_unplaced_finding():
    assert finding(suggestion(segment=None, overlap=0.0)).segment is None


def test_unknown_angles_are_allowed():
    f = finding_from_suggestion(suggestion(), series_uid="2.25.1", frame=0, primary_angle=None, secondary_angle=None, models=[])
    assert f.evidence.primary_angle is None and f.models == []


def test_proposals_are_one_per_placed_segment_in_order_of_first_appearance_and_cite_their_findings():
    fs = [finding(suggestion("6", 0.9)), finding(suggestion("6", 0.6)), finding(suggestion("11", 0.7)),
          finding(suggestion(None, 0.95, overlap=0.0))]
    proposals = proposals_from_findings(fs)
    assert [p.form.segments for p in proposals] == [["6"], ["11"]]
    assert [len(p.findings) for p in proposals] == [2, 1] and all(p.source == "ai" for p in proposals)
    assert [f.score for f in proposals[0].findings] == [0.9, 0.6]


def test_a_proposal_fills_in_the_segment_and_nothing_else():
    form = proposals_from_findings([finding()])[0].form
    answers = {k: v for k, v in form.model_dump().items() if k != "segments"}
    assert all(v is None for v in answers.values())


def test_no_findings_or_only_unplaced_ones_give_no_proposals():
    assert proposals_from_findings([]) == []
    assert proposals_from_findings([finding(suggestion(None, overlap=0.0))]) == []
