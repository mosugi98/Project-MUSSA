from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


# =====================================================================
# 1. ENUMS & CLINICAL CONSTANTS (SYNTAX SCORE I)
# =====================================================================

class Dominance(str, Enum):
    RIGHT = "right"
    LEFT = "left"


class SegmentID(str, Enum):
    SEG_1 = "1"      # RCA proximal
    SEG_2 = "2"      # RCA mid
    SEG_3 = "3"      # RCA distal
    SEG_4 = "4"      # Posterior descending artery (RCA)
    SEG_16 = "16"    # Posterolateral branch from RCA
    SEG_16A = "16a"  # Posterolateral branch from RCA (a)
    SEG_16B = "16b"  # Posterolateral branch from RCA (b)
    SEG_16C = "16c"  # Posterolateral branch from RCA (c)
    SEG_5 = "5"      # Left main
    SEG_6 = "6"      # LAD proximal
    SEG_7 = "7"      # LAD mid
    SEG_8 = "8"      # LAD apical
    SEG_9 = "9"      # First diagonal
    SEG_9A = "9a"    # First diagonal (a)
    SEG_10 = "10"    # Second diagonal
    SEG_10A = "10a"  # Second diagonal (a)
    SEG_11 = "11"    # Proximal circumflex
    SEG_12 = "12"    # Intermediate / anterolateral
    SEG_12A = "12a"  # Obtuse marginal (a)
    SEG_12B = "12b"  # Obtuse marginal (b)
    SEG_13 = "13"    # Distal circumflex
    SEG_14 = "14"    # Left posterolateral
    SEG_14A = "14a"  # Left posterolateral (a)
    SEG_14B = "14b"  # Left posterolateral (b)
    SEG_15 = "15"    # Posterior descending (Left)


SEGMENT_WEIGHTS: Dict[Dominance, Dict[SegmentID, float]] = {
    Dominance.RIGHT: {
        SegmentID.SEG_1: 1.0,
        SegmentID.SEG_2: 1.0,
        SegmentID.SEG_3: 1.0,
        SegmentID.SEG_4: 1.0,
        SegmentID.SEG_16: 0.5,
        SegmentID.SEG_16A: 0.5,
        SegmentID.SEG_16B: 0.5,
        SegmentID.SEG_16C: 0.5,
        SegmentID.SEG_5: 5.0,
        SegmentID.SEG_6: 3.5,
        SegmentID.SEG_7: 2.5,
        SegmentID.SEG_8: 1.0,
        SegmentID.SEG_9: 1.0,
        SegmentID.SEG_9A: 1.0,
        SegmentID.SEG_10: 0.5,
        SegmentID.SEG_10A: 0.5,
        SegmentID.SEG_11: 1.5,
        SegmentID.SEG_12: 1.0,
        SegmentID.SEG_12A: 1.0,
        SegmentID.SEG_12B: 1.0,
        SegmentID.SEG_13: 0.5,
        SegmentID.SEG_14: 0.5,
        SegmentID.SEG_14A: 0.5,
        SegmentID.SEG_14B: 0.5,
        SegmentID.SEG_15: 0.0,
    },
    Dominance.LEFT: {
        SegmentID.SEG_1: 0.0,
        SegmentID.SEG_2: 0.0,
        SegmentID.SEG_3: 0.0,
        SegmentID.SEG_4: 0.0,
        SegmentID.SEG_16: 0.0,
        SegmentID.SEG_16A: 0.0,
        SegmentID.SEG_16B: 0.0,
        SegmentID.SEG_16C: 0.0,
        SegmentID.SEG_5: 6.0,
        SegmentID.SEG_6: 3.5,
        SegmentID.SEG_7: 2.5,
        SegmentID.SEG_8: 1.0,
        SegmentID.SEG_9: 1.0,
        SegmentID.SEG_9A: 1.0,
        SegmentID.SEG_10: 0.5,
        SegmentID.SEG_10A: 0.5,
        SegmentID.SEG_11: 2.5,
        SegmentID.SEG_12: 1.0,
        SegmentID.SEG_12A: 1.0,
        SegmentID.SEG_12B: 1.0,
        SegmentID.SEG_13: 1.5,
        SegmentID.SEG_14: 1.0,
        SegmentID.SEG_14A: 1.0,
        SegmentID.SEG_14B: 1.0,
        SegmentID.SEG_15: 1.0,
    },
}


class MedinaClassification(str, Enum):
    TYPE_1_0_0 = "1,0,0"
    TYPE_0_1_0 = "0,1,0"
    TYPE_1_1_0 = "1,1,0"
    TYPE_1_1_1 = "1,1,1"
    TYPE_0_0_1 = "0,0,1"
    TYPE_1_0_1 = "1,0,1"
    TYPE_0_1_1 = "0,1,1"


class OcclusionSideBranch(str, Enum):
    NONE = "none"
    SMALL_ONLY = "sb_lt_1_5mm"          # +1 pt
    LARGE_ONLY = "sb_ge_1_5mm"          # 0 pt (scored as bifurcation instead)
    BOTH_SMALL_AND_LARGE = "both_sb"    # +1 pt


class RiskCategory(str, Enum):
    LOW = "low"                  # 0 - 22
    INTERMEDIATE = "intermediate"  # 23 - 32
    HIGH = "high"                # >= 33


# =====================================================================
# 2. DATA CONTRACT SCHEMAS (CV -> AGENT -> SCORER -> XA VIEWER)
# =====================================================================

class ViewEvidence(BaseModel):
    """Links an AI finding directly to a specific DICOM XA frame for Evidence Jump."""
    series_instance_uid: str
    sop_instance_uid: str
    frame_index: int = Field(..., ge=0)
    primary_angle_deg: float = Field(..., description="LAO (+) / RAO (-) angle")
    secondary_angle_deg: float = Field(..., description="Cranial (+) / Caudal (-) angle")
    bbox_xyxy: Optional[List[float]] = Field(None, min_length=4, max_length=4)
    qca_stenosis_percent: float = Field(..., ge=50.0, le=100.0)
    reference_vessel_diameter_mm: float = Field(..., ge=1.5)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    needs_attention: bool = Field(
        default=False,
        description="True if low SNR, vessel overlap, or borderline QCA requires physician focus."
    )


class InvolvedSegment(BaseModel):
    segment_id: SegmentID
    is_total_occlusion: bool = Field(
        default=False,
        description="True if 100% occluded (x5 multiplier); False if 50-99% stenosis (x2 multiplier)."
    )


class TotalOcclusionDetails(BaseModel):
    age_gt_3_months_or_unknown: bool = False
    blunt_stump: bool = False
    bridging_collaterals: bool = False
    non_visible_segments_beyond_occlusion: int = Field(default=0, ge=0, le=10)
    side_branch_involvement: OcclusionSideBranch = OcclusionSideBranch.NONE


class BifurcationDetails(BaseModel):
    medina: MedinaClassification
    angulation_lt_70_deg: bool = Field(
        default=False,
        description="Angle < 70 degrees between distal main vessel and side branch (+1 pt)."
    )


class TrifurcationDetails(BaseModel):
    diseased_segments_count: int = Field(..., ge=1, le=4)


class LesionInput(BaseModel):
    lesion_id: str
    involved_segments: List[InvolvedSegment] = Field(..., min_length=1)

    # Lesion morphological modifiers
    total_occlusion_details: Optional[TotalOcclusionDetails] = None
    trifurcation: Optional[TrifurcationDetails] = None
    bifurcation: Optional[BifurcationDetails] = None
    is_aorto_ostial: bool = False
    has_severe_tortuosity: bool = False
    length_gt_20mm: bool = False
    has_heavy_calcification: bool = False
    has_thrombus: bool = False

    # Traceability & Audit Trail
    primary_evidence: Optional[ViewEvidence] = None
    supporting_views: List[ViewEvidence] = Field(default_factory=list)
    agent_reasoning: str = Field(
        default="",
        description="Clinical explanation generated by the Agentic AI for physician review."
    )
    verified_by_physician: bool = False

    @model_validator(mode="after")
    def validate_clinical_rules(self) -> "LesionInput":
        if self.trifurcation is not None and self.bifurcation is not None:
            raise ValueError(
                f"Lesion '{self.lesion_id}' cannot be scored as both a trifurcation and a bifurcation."
            )
        has_cto = any(seg.is_total_occlusion for seg in self.involved_segments)
        if not has_cto and self.total_occlusion_details is not None:
            raise ValueError(
                f"Lesion '{self.lesion_id}' has total_occlusion_details but no segment marked is_total_occlusion=True."
            )
        return self


class StudySyntaxInput(BaseModel):
    study_instance_uid: str
    dominance: Dominance
    lesions: List[LesionInput] = Field(default_factory=list)
    diffuse_disease_segments: List[SegmentID] = Field(
        default_factory=list,
        description="Segments with >=75% length having vessel diameter < 2.0 mm distal to a lesion (+1 pt each)."
    )


class LesionScoreBreakdown(BaseModel):
    lesion_id: str
    base_segment_score: float
    occlusion_modifier_score: float
    trifurcation_score: float
    bifurcation_score: float
    aorto_ostial_score: float
    tortuosity_score: float
    length_score: float
    calcification_score: float
    thrombus_score: float
    lesion_total_score: float


class StudySyntaxOutput(BaseModel):
    study_instance_uid: str
    dominance: Dominance
    lesion_breakdowns: List[LesionScoreBreakdown]
    diffuse_disease_score: float
    total_syntax_score: float
    risk_category: RiskCategory
    requires_physician_attention: bool


# =====================================================================
# 3. DETERMINISTIC SYNTAX SCORE I ENGINE
# =====================================================================

def _score_single_lesion(lesion: LesionInput, dominance: Dominance) -> LesionScoreBreakdown:
    weights_map = SEGMENT_WEIGHTS[dominance]

    # 1. Segment weighting * stenosis multiplier (x2 for 50-99%, x5 for 100% CTO)
    base_score = 0.0
    for seg in lesion.involved_segments:
        seg_weight = weights_map[seg.segment_id]
        multiplier = 5.0 if seg.is_total_occlusion else 2.0
        base_score += seg_weight * multiplier

    # 2. Total occlusion adverse characteristics
    occlusion_score = 0.0
    if lesion.total_occlusion_details is not None:
        cto = lesion.total_occlusion_details
        if cto.age_gt_3_months_or_unknown:
            occlusion_score += 1.0
        if cto.blunt_stump:
            occlusion_score += 1.0
        if cto.bridging_collaterals:
            occlusion_score += 1.0
        occlusion_score += float(cto.non_visible_segments_beyond_occlusion)
        if cto.side_branch_involvement in (
            OcclusionSideBranch.SMALL_ONLY,
            OcclusionSideBranch.BOTH_SMALL_AND_LARGE,
        ):
            occlusion_score += 1.0

    # 3. Trifurcation (+3 to +6)
    trifurcation_score = 0.0
    if lesion.trifurcation is not None:
        trifurcation_map = {1: 3.0, 2: 4.0, 3: 5.0, 4: 6.0}
        trifurcation_score = trifurcation_map[lesion.trifurcation.diseased_segments_count]

    # 4. Bifurcation (+1 or +2, plus +1 if angulation < 70 deg)
    bifurcation_score = 0.0
    if lesion.bifurcation is not None:
        medina_one_pt = {
            MedinaClassification.TYPE_1_0_0,
            MedinaClassification.TYPE_0_1_0,
            MedinaClassification.TYPE_1_1_0,
        }
        bifurcation_score += 1.0 if lesion.bifurcation.medina in medina_one_pt else 2.0
        if lesion.bifurcation.angulation_lt_70_deg:
            bifurcation_score += 1.0

    # 5. Other adverse lesion features
    aorto_ostial_score = 1.0 if lesion.is_aorto_ostial else 0.0
    tortuosity_score = 2.0 if lesion.has_severe_tortuosity else 0.0
    length_score = 1.0 if lesion.length_gt_20mm else 0.0
    calcification_score = 2.0 if lesion.has_heavy_calcification else 0.0
    thrombus_score = 1.0 if lesion.has_thrombus else 0.0

    lesion_total = (
        base_score
        + occlusion_score
        + trifurcation_score
        + bifurcation_score
        + aorto_ostial_score
        + tortuosity_score
        + length_score
        + calcification_score
        + thrombus_score
    )

    return LesionScoreBreakdown(
        lesion_id=lesion.lesion_id,
        base_segment_score=round(base_score, 2),
        occlusion_modifier_score=round(occlusion_score, 2),
        trifurcation_score=round(trifurcation_score, 2),
        bifurcation_score=round(bifurcation_score, 2),
        aorto_ostial_score=round(aorto_ostial_score, 2),
        tortuosity_score=round(tortuosity_score, 2),
        length_score=round(length_score, 2),
        calcification_score=round(calcification_score, 2),
        thrombus_score=round(thrombus_score, 2),
        lesion_total_score=round(lesion_total, 2),
    )


def calculate_syntax_score(study: StudySyntaxInput) -> StudySyntaxOutput:
    """
    Deterministic SYNTAX Score I calculator.
    Designed to be called as a tool by the Agentic Orchestrator and directly
    by the XA Viewer backend when a physician modifies lesion attributes.
    """
    breakdowns = [_score_single_lesion(lesion, study.dominance) for lesion in study.lesions]

    # Unique diffuse disease segments (+1 pt per segment)
    unique_diffuse_segments = set(study.diffuse_disease_segments)
    diffuse_score = float(len(unique_diffuse_segments))

    total_score = round(
        sum(b.lesion_total_score for b in breakdowns) + diffuse_score,
        2,
    )

    if total_score <= 22.0:
        risk = RiskCategory.LOW
    elif total_score <= 32.0:
        risk = RiskCategory.INTERMEDIATE
    else:
        risk = RiskCategory.HIGH

    needs_attention = any(
        (lesion.primary_evidence is not None and lesion.primary_evidence.needs_attention)
        for lesion in study.lesions
    )

    return StudySyntaxOutput(
        study_instance_uid=study.study_instance_uid,
        dominance=study.dominance,
        lesion_breakdowns=breakdowns,
        diffuse_disease_score=diffuse_score,
        total_syntax_score=total_score,
        risk_category=risk,
        requires_physician_attention=needs_attention,
    )