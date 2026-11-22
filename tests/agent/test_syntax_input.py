"""The supplied draft's scenarios, reproduced against the project's verified engine, plus the places where the
official rules (which the engine implements) differ from the draft."""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from cagsyntax.agent.adapters import AdapterError, lesion_input_to_lesion, score_study, study_to_case
from cagsyntax.agent.schema import (BifurcationDetails, InvolvedSegment, LesionInput, StudySyntaxInput,
                                    TotalOcclusionDetails, TrifurcationDetails, ViewEvidence)

ROOT = Path(__file__).resolve().parents[2]


def evidence(**kw):
    base = dict(series_instance_uid="1.2.840.1.1", sop_instance_uid="1.2.840.1.1.1", frame_index=42,
                primary_angle_deg=-15.0, secondary_angle_deg=35.0, bbox_xyxy=(120, 140, 210, 230),
                qca_stenosis_percent=75.4, reference_vessel_diameter_mm=3.2, confidence_score=0.94, needs_attention=False)
    base.update(kw)
    return ViewEvidence(**base)


def study(*lesions, dominance="right", diffuse=(), uid="1.2.840.1"):
    return StudySyntaxInput(study_instance_uid=uid, dominance=dominance, lesions=list(lesions),
                            diffuse_disease_segments=list(diffuse))


def seg(segment_id, occluded=False):
    return InvolvedSegment(segment_id=segment_id, is_total_occlusion=occluded)


# ---------------------------------------------------------------- the draft's own three scenarios
def test_right_dominant_proximal_lad_bifurcation_scores_13_low():
    out = score_study(study(LesionInput(
        lesion_id="L1_PROX_LAD", involved_segments=[seg("6")],
        bifurcation=BifurcationDetails(medina="1,1,1", angulation_lt_70_deg=True),
        length_gt_20mm=True, has_heavy_calcification=True, primary_evidence=evidence())))
    assert out.status == "complete" and out.total_syntax_score == 13.0 and out.risk_category == "low"
    assert out.requires_physician_attention is False


def test_left_dominant_lm_and_lcx_occlusion_scores_29_5_intermediate():
    """LM (6.0 x2 = 12) + ostial 1; proximal LCx occlusion 2.5 x5 = 12.5 + age 1 + blunt stump 1 + bridging 1 +
    1 for a segment not visualized beyond (the draft's typed count of 1 is, in the official form, 'the first
    segment visualized beyond is 14')."""
    out = score_study(study(
        LesionInput(lesion_id="L1_OSTIAL_LM", involved_segments=[seg("5")], is_aorto_ostial=True),
        LesionInput(lesion_id="L2_PROX_LCX_CTO", involved_segments=[seg("11", occluded=True)],
                    total_occlusion_details=TotalOcclusionDetails(
                        age_gt_3_months_or_unknown=True, blunt_stump=True, bridging_collaterals=True,
                        first_visualized_beyond="14", side_branch_involvement="none")),
        dominance="left"))
    assert out.status == "complete" and out.total_syntax_score == 29.5 and out.risk_category == "intermediate"


def test_a_lesion_over_two_segments_and_diffuse_disease_scores_14():
    out = score_study(study(LesionInput(lesion_id="L1", involved_segments=[seg("6"), seg("7")]), diffuse=["8", "10"]))
    assert out.total_syntax_score == 14.0 and out.diffuse_disease_score == 2.0


def test_a_lesion_cannot_be_both_a_bifurcation_and_a_trifurcation():
    with pytest.raises(ValidationError):
        LesionInput(lesion_id="BAD", involved_segments=[seg("5")], bifurcation=BifurcationDetails(medina="1,1,1"),
                    trifurcation=TrifurcationDetails(diseased_segments_count=2))


def test_occlusion_details_need_an_occluded_segment():
    with pytest.raises(ValidationError):
        LesionInput(lesion_id="BAD", involved_segments=[seg("6")], total_occlusion_details=TotalOcclusionDetails())


# ---------------------------------------------------------------- where the official rules win over the draft
def occlusion_lesion(segments, **kw):
    return LesionInput(lesion_id="CTO", involved_segments=segments,
                       total_occlusion_details=TotalOcclusionDetails(
                           age_gt_3_months_or_unknown=False, blunt_stump=False, bridging_collaterals=False,
                           first_visualized_beyond="none", side_branch_involvement="none"), **kw)


def test_only_the_first_segment_of_an_occlusion_counts_times_five():
    out = score_study(study(occlusion_lesion([seg("6", occluded=True), seg("7")])))
    # 3.5 x5 + 2.5 x2 = 22.5, plus 2 for nothing visualized beyond: the draft's "every flagged segment x5" would differ
    assert out.status == "complete" and out.total_syntax_score == 24.5


def test_two_segments_flagged_as_occluded_in_one_lesion_are_refused_with_an_explanation():
    with pytest.raises(AdapterError) as exc:
        study_to_case(study(occlusion_lesion([seg("6", occluded=True), seg("7", occluded=True)])))
    assert "first segment" in str(exc.value) and "CTO" in str(exc.value)


def test_a_segment_count_is_not_accepted_in_place_of_the_first_visualized_segment():
    assert not hasattr(TotalOcclusionDetails(), "non_visible_segments_beyond_occlusion")


def test_aorto_ostial_on_segment_8_is_reported_invalid_not_scored():
    out = score_study(study(LesionInput(lesion_id="L8", involved_segments=[seg("8")], is_aorto_ostial=True)))
    assert out.status == "invalid" and out.total_syntax_score is None and out.risk_category is None
    assert [(i.code, i.lesion_id) for i in out.issues] == [("ostial_not_applicable", "L8")]
    assert out.requires_physician_attention is True


def test_length_over_20_mm_on_an_occlusion_is_reported_invalid():
    out = score_study(study(occlusion_lesion([seg("6", occluded=True)], length_gt_20mm=True)))
    assert out.status == "invalid" and out.issues[0].code == "length_with_occlusion"


def test_a_plain_lesion_with_no_extra_findings_is_scored_without_asking_for_answers():
    out = score_study(study(LesionInput(lesion_id="L1", involved_segments=[seg("8")])))
    assert out.status == "complete" and out.total_syntax_score == 2.0              # weight 1.0 x2


def test_an_occlusion_with_default_bifurcation_and_trifurcation_values_is_still_complete():
    out = score_study(study(occlusion_lesion([seg("6", occluded=True)])))
    assert out.status == "complete" and out.total_syntax_score == 19.5


def test_a_small_side_branch_at_the_origin_of_an_occlusion_adds_one_point():
    def total(branch):
        lesion = LesionInput(lesion_id="CTO", involved_segments=[seg("6", occluded=True)],
                             total_occlusion_details=TotalOcclusionDetails(
                                 age_gt_3_months_or_unknown=False, blunt_stump=False, bridging_collaterals=False,
                                 first_visualized_beyond="none", side_branch_involvement=branch))
        return score_study(study(lesion)).total_syntax_score
    assert total("sb_lt_1_5mm") == total("none") + 1 == total("both_sb")


def test_co_dominance_needs_a_scoring_table_like_the_engine_requires():
    s = StudySyntaxInput(study_instance_uid="1", dominance="co-dominant",
                         lesions=[LesionInput(lesion_id="L1", involved_segments=[seg("6")])])
    assert score_study(s).status == "incomplete"
    s.scoring_dominance = "right"
    assert score_study(s).status == "complete"


# ---------------------------------------------------------------- AI-proposed (draft) lesions
def test_a_draft_lesion_stays_incomplete_and_has_no_total_until_answered():
    out = score_study(study(LesionInput(lesion_id="AI_1", involved_segments=[seg("6")], draft=True)))
    assert out.status == "incomplete" and out.total_syntax_score is None and out.risk_category is None
    assert out.issues and out.requires_physician_attention is True


def test_a_draft_lesion_carries_the_segment_and_no_answers():
    lesion = lesion_input_to_lesion(LesionInput(lesion_id="AI_1", involved_segments=[seg("6")], draft=True), "right")
    assert lesion.segments == ["6"] and lesion.occlusion is None and lesion.bifurcation is None
    assert lesion.length_gt20 is None and lesion.thrombus is None


def test_flagged_evidence_asks_for_the_physicians_attention_even_when_the_score_is_complete():
    out = score_study(study(LesionInput(lesion_id="L1", involved_segments=[seg("8")],
                                        primary_evidence=evidence(needs_attention=True))))
    assert out.status == "complete" and out.requires_physician_attention is True


# ---------------------------------------------------------------- the output explains itself
def test_the_breakdown_is_the_engines_own_explanation_and_adds_up():
    out = score_study(study(LesionInput(lesion_id="L1_PROX_LAD", involved_segments=[seg("6")],
                                        bifurcation=BifurcationDetails(medina="1,1,1", angulation_lt_70_deg=True),
                                        length_gt_20mm=True, has_heavy_calcification=True)))
    b = out.lesion_breakdowns[0]
    assert b.lesion_id == "L1_PROX_LAD" and b.lesion_total_score == 13.0
    assert ("Bifurcation angle under 70 degrees", 1.0) in [(p.label, p.points) for p in b.parts]
    assert sum(p.points for p in b.parts) == b.lesion_total_score
    assert out.engine_version.startswith("official calculator")


def test_the_study_converts_to_the_engines_case():
    case = study_to_case(study(LesionInput(lesion_id="L1", involved_segments=[seg("6"), seg("7")]), diffuse=["8"],
                               dominance="left"))
    assert case.dominance == "left" and case.lesions[0].segments == ["6", "7"] and case.diffuse_segments == ["8"]


# ---------------------------------------------------------------- evidence: what is measured, what is not
def test_evidence_accepts_unmeasured_values_as_unknown():
    e = ViewEvidence(series_instance_uid="1.1", sop_instance_uid="1.1.1", frame_index=0, confidence_score=0.7)
    assert e.primary_angle_deg is None and e.qca_stenosis_percent is None and e.reference_vessel_diameter_mm is None
    assert e.bbox_xyxy is None and e.needs_attention is False


def test_evidence_refuses_unrealistic_values_when_they_are_given():
    for bad in (dict(qca_stenosis_percent=40.0), dict(qca_stenosis_percent=101.0), dict(reference_vessel_diameter_mm=1.0),
                dict(frame_index=-1), dict(confidence_score=1.5), dict(bbox_xyxy=(10, 10, 5, 20)),
                dict(primary_angle_deg=200.0)):
        with pytest.raises(ValidationError):
            evidence(**bad)


def test_a_segment_must_be_one_of_the_25_sub_segments():
    with pytest.raises(ValidationError):
        InvolvedSegment(segment_id="17")
    from cagsyntax.ai.segment_names import SEGMENT_NAMES
    assert all(InvolvedSegment(segment_id=name).segment_id == name for name in SEGMENT_NAMES)


# ---------------------------------------------------------------- housekeeping
def test_the_supplied_draft_is_kept_as_reference_and_not_imported():
    reference = ROOT / "docs" / "reference" / "agentic-draft"
    assert {p.name for p in reference.glob("*.py")} >= {"syntax_engine.py", "orchestrator.py", "test_syntax_engine.py"}
    assert not [p for p in ROOT.glob("*.py")]                                        # nothing stray in the project root
    assert not any(name.startswith(("langchain", "langgraph", "openai")) for name in sys.modules)
