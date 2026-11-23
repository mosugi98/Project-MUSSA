"""Types of the agentic SYNTAX layer, named after the supplied draft and built on the project's contract.

What differs from the draft, and why:
  - nothing a model cannot measure is required: QCA %, vessel diameter, lesion length, morphology hints, SNR and
    C-arm angles are None when unknown (an invented 0 or False would look like a finding);
  - occlusion follows the official form: one first segment (x5), and "the first segment visualized beyond the
    occlusion" instead of a typed count of non-visible segments;
  - a lesion proposed by the AI is a `draft`: the segment only, every question left for the scorer;
  - the output carries the engine's own status, issues and explanation, and a total of None when the case is not
    complete (never a silent 0).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..contract.models import Angle, ContractModel, ModelRef, Probability, Segment, _segment

Dominance = Literal["right", "left", "co-dominant"]
Medina = Literal["1,0,0", "0,1,0", "1,1,0", "1,1,1", "0,0,1", "1,0,1", "0,1,1"]
OcclusionSideBranch = Literal["none", "sb_lt_1_5mm", "sb_ge_1_5mm", "both_sb"]
RiskCategory = Literal["low", "intermediate", "high"]
Status = Literal["complete", "incomplete", "invalid"]
Box = tuple[int, int, int, int]


def _check_box(box: Box | None) -> Box | None:
    if box is not None:
        x0, y0, x1, y1 = box
        if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
            raise ValueError("a box needs 0 <= x0 < x1 and 0 <= y0 < y1 (integer pixels, x1 and y1 exclusive)")
    return box


# ---------------------------------------------------------------- evidence
class ViewEvidence(ContractModel):
    """Links a finding to one frame of one DICOM run, for the evidence jump. Measurements are None until measured."""
    series_instance_uid: str = Field(min_length=1)
    sop_instance_uid: str = Field(min_length=1)
    frame_index: int = Field(ge=0)
    primary_angle_deg: Angle | None = None              # LAO (+) / RAO (-)
    secondary_angle_deg: Angle | None = None            # cranial (+) / caudal (-)
    bbox_xyxy: Box | None = None                        # integer pixels of the frame, x1 and y1 exclusive
    qca_stenosis_percent: float | None = Field(default=None, ge=50.0, le=100.0)
    reference_vessel_diameter_mm: float | None = Field(default=None, ge=1.5)
    confidence_score: Probability
    needs_attention: bool = False

    @field_validator("bbox_xyxy")
    @classmethod
    def _box(cls, box):
        return _check_box(box)


# ---------------------------------------------------------------- lesions
class InvolvedSegment(ContractModel):
    segment_id: Segment
    is_total_occlusion: bool = False                    # mark only the FIRST segment of an occlusion


class TotalOcclusionDetails(ContractModel):
    age_gt_3_months_or_unknown: bool = False
    blunt_stump: bool = False
    bridging_collaterals: bool = False
    first_visualized_beyond: str | None = None          # a segment id, or "none"; None = not answered yet
    side_branch_involvement: OcclusionSideBranch = "none"

    @field_validator("first_visualized_beyond")
    @classmethod
    def _beyond(cls, value):
        if value is not None and value != "none":
            _segment(value)
        return value


class BifurcationDetails(ContractModel):
    medina: Medina
    angulation_lt_70_deg: bool = False


class TrifurcationDetails(ContractModel):
    diseased_segments_count: int = Field(ge=1, le=4)


class LesionInput(ContractModel):
    lesion_id: str = Field(min_length=1)
    involved_segments: list[InvolvedSegment] = Field(min_length=1)
    total_occlusion_details: TotalOcclusionDetails | None = None
    trifurcation: TrifurcationDetails | None = None
    bifurcation: BifurcationDetails | None = None
    is_aorto_ostial: bool = False
    has_severe_tortuosity: bool = False
    length_gt_20mm: bool = False
    has_heavy_calcification: bool = False
    has_thrombus: bool = False
    primary_evidence: ViewEvidence | None = None
    supporting_views: list[ViewEvidence] = Field(default_factory=list)
    agent_reasoning: str = ""
    verified_by_physician: bool = False
    draft: bool = False                                 # AI-proposed: segment only, every answer left to the scorer

    @model_validator(mode="after")
    def _clinical_rules(self):
        if self.trifurcation is not None and self.bifurcation is not None:
            raise ValueError(f"Lesion '{self.lesion_id}' cannot be scored as both a trifurcation and a bifurcation.")
        ids = [s.segment_id for s in self.involved_segments]
        if len(set(ids)) != len(ids):
            raise ValueError(f"Lesion '{self.lesion_id}' lists a segment more than once.")
        if self.total_occlusion_details is not None and not any(s.is_total_occlusion for s in self.involved_segments):
            raise ValueError(f"Lesion '{self.lesion_id}' has total_occlusion_details but no segment marked "
                             "is_total_occlusion=True.")
        return self


class StudySyntaxInput(ContractModel):
    study_instance_uid: str = Field(min_length=1)
    dominance: Dominance | None = None                  # None = not decided yet (the engine then asks for it)
    scoring_dominance: Literal["right", "left"] | None = None      # required by the engine when co-dominant
    lesions: list[LesionInput] = Field(default_factory=list)
    diffuse_disease_segments: list[Segment] = Field(default_factory=list)


# ---------------------------------------------------------------- the engine's answer
class PartRecord(ContractModel):
    label: str
    points: float


class IssueItem(ContractModel):
    code: str
    message: str
    lesion_id: str | None = None


class LesionBreakdown(ContractModel):
    lesion_id: str
    parts: list[PartRecord]                              # the engine's own explanation, line by line
    lesion_total_score: float


class StudySyntaxOutput(ContractModel):
    study_instance_uid: str
    dominance: Dominance | None = None
    status: Status
    issues: list[IssueItem] = Field(default_factory=list)
    lesion_breakdowns: list[LesionBreakdown] = Field(default_factory=list)
    diffuse_disease_score: float = 0.0
    total_syntax_score: float | None = None              # None unless the case is complete
    risk_category: RiskCategory | None = None
    requires_physician_attention: bool
    engine_version: str


# ---------------------------------------------------------------- what the vision models report per run
class RawCVLesionCandidate(ContractModel):
    """One candidate narrowing on one frame. Only what the models actually produce is required."""
    candidate_id: str = Field(min_length=1)
    predicted_segment: Segment | None = None            # None: outside every outlined segment
    stenosis_score: Probability                         # the stenosis model's score (not a calibrated certainty)
    segment_overlap: Probability                        # share of the candidate inside predicted_segment
    series_instance_uid: str = Field(min_length=1)
    sop_instance_uid: str = Field(min_length=1)
    frame_index: int = Field(ge=0)
    primary_angle_deg: Angle | None = None
    secondary_angle_deg: Angle | None = None
    bbox_xyxy: Box | None = None
    pixels: int = Field(ge=0)
    # not measured by any current model; None = unknown
    qca_stenosis_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    reference_vessel_diameter_mm: float | None = Field(default=None, gt=0.0)
    lesion_length_mm: float | None = Field(default=None, ge=0.0)
    is_total_occlusion: bool | None = None
    is_bifurcation_candidate: bool | None = None
    has_calcification_hint: bool | None = None
    has_thrombus_hint: bool | None = None
    image_snr_score: Probability | None = None

    @field_validator("bbox_xyxy")
    @classmethod
    def _box(cls, box):
        return _check_box(box)


class RunPerceptionSummary(ContractModel):
    """Everything the vision models reported for one angiographic run (series)."""
    series_instance_uid: str = Field(min_length=1)
    sop_instance_uid: str = Field(min_length=1)
    study_instance_uid: str | None = None                # the de-identified study; reconciliation refuses to mix studies
    view_label: str
    frame_count: int = Field(ge=1)
    analysed_frames: list[int] = Field(default_factory=list)
    visible_segments: list[Segment] = Field(default_factory=list)
    pda_origin_detected: Literal["right", "left"] | None = None      # no model detects this yet
    candidates: list[RawCVLesionCandidate] = Field(default_factory=list)
    models: list[ModelRef] = Field(default_factory=list)             # the model files that produced this run
