"""The shared data contract: one schema for vision output, reconciliation, the SYNTAX engine and review.

Rules that hold for every model here:
  - unknown fields and unknown option strings are refused (a typo must fail loudly, not be ignored);
  - segment names are exactly the 25 sub-segments of the SYNTAX tables;
  - nothing identifies a patient: UIDs are the de-identified ones and reviewers are store ids;
  - a score in this file is a read-only snapshot of the engine's result, never an input to scoring.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from ..ai.segment_names import SEGMENT_NAMES

SCHEMA_VERSION = "1.0"


def _segment(value: str) -> str:
    if value not in SEGMENT_NAMES:
        raise ValueError(f"{value!r} is not one of the 25 SYNTAX segments")
    return value


Segment = Annotated[str, AfterValidator(_segment)]
Angle = Annotated[float, Field(ge=-180.0, le=180.0)]
Probability = Annotated[float, Field(ge=0.0, le=1.0)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- provenance
class ModelRef(ContractModel):
    """Which model file produced something: its role and its identity (training date and file hash)."""
    name: Literal["segments", "stenosis"]
    identity: str = Field(min_length=1)


class Evidence(ContractModel):
    """Where a finding comes from: series, frame, C-arm angles and a box (x0, y0, x1, y1; x1 and y1 exclusive)."""
    series_uid: str = Field(min_length=1)
    frame: int = Field(ge=0)
    primary_angle: Angle | None = None          # LAO (+) / RAO (-)
    secondary_angle: Angle | None = None        # cranial (+) / caudal (-)
    box: tuple[int, int, int, int] | None = None

    @field_validator("box")
    @classmethod
    def _box(cls, box):
        if box is not None:
            x0, y0, x1, y1 = box
            if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
                raise ValueError("a box needs 0 <= x0 < x1 and 0 <= y0 < y1")
        return box


class Finding(ContractModel):
    """One candidate narrowing seen on one frame, as the vision models reported it."""
    evidence: Evidence
    segment: Segment | None = None              # None: outside every outlined segment ("unplaced")
    score: Probability                          # the model's score, not a calibrated certainty
    pixels: int = Field(ge=0)
    overlap: Probability                        # share of the candidate inside `segment`
    models: list[ModelRef] = Field(default_factory=list)


# ---------------------------------------------------------------- the scoring form
class LesionForm(ContractModel):
    """The questions of one lesion, exactly as the engine's `Lesion` has them. None = not answered (a draft)."""
    segments: list[Segment]
    occlusion: bool | None = None
    first_segment: Segment | None = None
    age_over_3_months: Literal["no", "yes", "unknown"] | None = None
    blunt_stump: bool | None = None
    bridging: bool | None = None
    beyond_first_visualized: str | None = None          # a segment, or "none"
    side_branch: Literal["no", "small", "large", "both"] | None = None
    trifurcation: int | None = Field(default=None, ge=0, le=4)
    bifurcation: Literal["none", "A", "B", "C", "D", "E", "F", "G"] | None = None
    bifurcation_angle_lt70: bool | None = None
    aorto_ostial: bool | None = None
    severe_tortuosity: bool | None = None
    length_gt20: bool | None = None
    heavy_calcification: bool | None = None
    thrombus: bool | None = None

    @field_validator("segments")
    @classmethod
    def _unique_segments(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("a segment may appear only once in a lesion")
        return value

    @field_validator("beyond_first_visualized")
    @classmethod
    def _beyond(cls, value):
        if value is not None and value != "none":
            _segment(value)
        return value


class CaseForm(ContractModel):
    dominance: Literal["right", "left", "co-dominant"] | None = None
    scoring_dominance: Literal["right", "left"] | None = None
    lesions: list[LesionForm]
    diffuse_segments: list[Segment] = Field(default_factory=list)

    @field_validator("diffuse_segments")
    @classmethod
    def _unique_diffuse(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("a segment may appear only once among the diffuse segments")
        return value


class LesionProposal(ContractModel):
    """A lesion someone proposes, with the findings that support it. An AI proposal must cite findings."""
    form: LesionForm
    findings: list[Finding] = Field(default_factory=list)
    source: Literal["ai", "physician"]

    @model_validator(mode="after")
    def _ai_cites_evidence(self):
        if self.source == "ai" and not self.findings:
            raise ValueError("an AI proposal must cite at least one finding")
        return self


class Review(ContractModel):
    """The AI's raw prediction is kept as it was; the physician's approved answer is stored next to it."""
    ai_raw_prediction: CaseForm | None = None
    physician_final_approved: CaseForm | None = None
    reviewer_id: int | None = None
    reviewer_level: Literal["resident", "cardiologist"] | None = None
    reviewed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _final_answer_has_an_author(self):
        if self.physician_final_approved is not None and (
                self.reviewer_id is None or self.reviewer_level is None or self.reviewed_at is None):
            raise ValueError("an approved final answer needs reviewer_id, reviewer_level and reviewed_at")
        return self


# ---------------------------------------------------------------- the engine's answer (read-only)
class IssueRecord(ContractModel):
    code: str
    message: str
    lesion: int | None = None


class ScoreSummary(ContractModel):
    """A snapshot of what the SYNTAX engine returned. Never an input: to score, convert the form and run the engine."""
    status: Literal["complete", "incomplete", "invalid"]
    total: float | None = Field(default=None, ge=0)
    group: str | None = None
    engine_version: str = Field(min_length=1)
    issues: list[IssueRecord] = Field(default_factory=list)
    lesion_totals: list[float] = Field(default_factory=list)
    diffuse_points: float = 0.0


# ---------------------------------------------------------------- the whole document
class SeriesInfo(ContractModel):
    series_uid: str = Field(min_length=1)
    kind: Literal["cine", "still"]
    frame_count: int = Field(ge=1)
    fps: float | None = Field(default=None, gt=0)
    primary_angle: Angle | None = None
    secondary_angle: Angle | None = None


class CaseAnalysis(ContractModel):
    """Everything known about one study: its series, what the models found, proposals, review and score."""
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    study_uid: str = Field(min_length=1)
    series: list[SeriesInfo] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    proposals: list[LesionProposal] = Field(default_factory=list)
    review: Review | None = None
    score: ScoreSummary | None = None
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _traceable(self):
        frames = {}
        for s in self.series:
            if s.series_uid in frames:
                raise ValueError(f"series {s.series_uid} is listed twice")
            frames[s.series_uid] = s.frame_count
        cited = list(self.findings) + [f for p in self.proposals for f in p.findings]
        for finding in cited:
            e = finding.evidence
            if e.series_uid not in frames:
                raise ValueError(f"evidence points at series {e.series_uid}, which is not in this analysis")
            if e.frame >= frames[e.series_uid]:
                raise ValueError(f"evidence points at frame {e.frame} of series {e.series_uid}, "
                                 f"which has only {frames[e.series_uid]} frames")
        return self
