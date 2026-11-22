import pytest
from pydantic import ValidationError

from app.scoring.syntax_engine import (
    BifurcationDetails,
    Dominance,
    InvolvedSegment,
    LesionInput,
    MedinaClassification,
    OcclusionSideBranch,
    RiskCategory,
    SegmentID,
    StudySyntaxInput,
    TotalOcclusionDetails,
    TrifurcationDetails,
    ViewEvidence,
    calculate_syntax_score,
)


def test_right_dominant_proximal_lad_bifurcation():
    """
    Seg 6 (Proximal LAD, weight 3.5) with 75% stenosis (x2 = 7.0),
    Bifurcation Medina 1,1,1 (+2) + angle < 70 deg (+1),
    Length > 20 mm (+1), Heavy calcification (+2) -> Expected Total = 13.0 (Low Risk).
    """
    study = StudySyntaxInput(
        study_instance_uid="1.2.840.113619.2.55.1",
        dominance=Dominance.RIGHT,
        lesions=[
            LesionInput(
                lesion_id="L1_PROX_LAD",
                involved_segments=[
                    InvolvedSegment(segment_id=SegmentID.SEG_6, is_total_occlusion=False)
                ],
                bifurcation=BifurcationDetails(
                    medina=MedinaClassification.TYPE_1_1_1,
                    angulation_lt_70_deg=True,
                ),
                length_gt_20mm=True,
                has_heavy_calcification=True,
                primary_evidence=ViewEvidence(
                    series_instance_uid="1.2.840.113619.2.55.1.1",
                    sop_instance_uid="1.2.840.113619.2.55.1.1.1",
                    frame_index=42,
                    primary_angle_deg=-15.0,
                    secondary_angle_deg=35.0,
                    bbox_xyxy=[120.0, 140.0, 210.0, 230.0],
                    qca_stenosis_percent=75.4,
                    reference_vessel_diameter_mm=3.2,
                    confidence_score=0.94,
                    needs_attention=False,
                ),
            )
        ],
    )

    result = calculate_syntax_score(study)
    assert result.total_syntax_score == 13.0
    assert result.risk_category == RiskCategory.LOW
    assert result.requires_physician_attention is False


def test_left_dominant_lm_and_lcx_cto():
    """
    Left Dominant:
    - Lesion 1: Seg 5 (LM, weight 6.0) 60% stenosis (x2 = 12.0) + Ostial (+1) = 13.0
    - Lesion 2: Seg 11 (Prox LCx, weight 2.5) 100% CTO (x5 = 12.5)
      + age > 3m (+1) + blunt stump (+1) + bridging (+1) + 1 non-visible seg (+1) = 16.5
    Expected Total = 29.5 (Intermediate Risk).
    """
    study = StudySyntaxInput(
        study_instance_uid="1.2.840.113619.2.55.2",
        dominance=Dominance.LEFT,
        lesions=[
            LesionInput(
                lesion_id="L1_OSTIAL_LM",
                involved_segments=[
                    InvolvedSegment(segment_id=SegmentID.SEG_5, is_total_occlusion=False)
                ],
                is_aorto_ostial=True,
            ),
            LesionInput(
                lesion_id="L2_PROX_LCX_CTO",
                involved_segments=[
                    InvolvedSegment(segment_id=SegmentID.SEG_11, is_total_occlusion=True)
                ],
                total_occlusion_details=TotalOcclusionDetails(
                    age_gt_3_months_or_unknown=True,
                    blunt_stump=True,
                    bridging_collaterals=True,
                    non_visible_segments_beyond_occlusion=1,
                    side_branch_involvement=OcclusionSideBranch.NONE,
                ),
            ),
        ],
    )

    result = calculate_syntax_score(study)
    assert result.total_syntax_score == 29.5
    assert result.risk_category == RiskCategory.INTERMEDIATE


def test_multi_segment_lesion_and_diffuse_disease():
    """
    Right Dominant:
    - Single continuous lesion spanning Seg 6 (3.5) and Seg 7 (2.5) at 80% stenosis (x2) = 12.0
    - Diffuse disease in Seg 8 and Seg 10 (+2.0)
    Expected Total = 14.0.
    """
    study = StudySyntaxInput(
        study_instance_uid="1.2.840.113619.2.55.3",
        dominance=Dominance.RIGHT,
        lesions=[
            LesionInput(
                lesion_id="L1_PROX_MID_LAD",
                involved_segments=[
                    InvolvedSegment(segment_id=SegmentID.SEG_6, is_total_occlusion=False),
                    InvolvedSegment(segment_id=SegmentID.SEG_7, is_total_occlusion=False),
                ],
            )
        ],
        diffuse_disease_segments=[SegmentID.SEG_8, SegmentID.SEG_10],
    )

    result = calculate_syntax_score(study)
    assert result.total_syntax_score == 14.0
    assert result.diffuse_disease_score == 2.0


def test_guardrail_rejects_simultaneous_bifurcation_and_trifurcation():
    """Ensures Pydantic catches invalid LLM tool-call combinations."""
    with pytest.raises(ValidationError):
        LesionInput(
            lesion_id="INVALID_LESION",
            involved_segments=[InvolvedSegment(segment_id=SegmentID.SEG_5)],
            bifurcation=BifurcationDetails(medina=MedinaClassification.TYPE_1_1_1),
            trifurcation=TrifurcationDetails(diseased_segments_count=2),
        )