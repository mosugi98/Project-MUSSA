from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Lesion:
    """One lesion. None means "not answered". Only questions that apply need an answer."""
    segments: list[str]
    occlusion: bool | None = None
    first_segment: str | None = None              # occlusion: first segment of the T.O. (one only)
    age_over_3_months: str | None = None          # "no" | "yes" | "unknown"
    blunt_stump: bool | None = None
    bridging: bool | None = None
    beyond_first_visualized: str | None = None    # segment id, or "none"
    side_branch: str | None = None                # "no" | "small" | "large" | "both"
    trifurcation: int | None = None               # 0 = no, 1..4 = diseased segments involved
    bifurcation: str | None = None                # "none" or Medina "A".."G"
    bifurcation_angle_lt70: bool | None = None
    aorto_ostial: bool | None = None
    severe_tortuosity: bool | None = None
    length_gt20: bool | None = None
    heavy_calcification: bool | None = None
    thrombus: bool | None = None


@dataclass
class Case:
    dominance: str | None                 # "right" | "left" | "co-dominant"
    scoring_dominance: str | None         # "right" | "left"; required when co-dominant
    lesions: list[Lesion]
    diffuse_segments: list[str] = field(default_factory=list)


@dataclass
class Issue:
    code: str
    message: str
    lesion: int | None = None             # 0-based lesion index, None for case-level


@dataclass
class Part:
    label: str
    points: float


@dataclass
class LesionResult:
    total: float
    parts: list[Part]


@dataclass
class CaseResult:
    status: str                           # "complete" | "incomplete" | "invalid"
    issues: list[Issue]
    total: float | None
    group: str | None
    dominance: str | None
    scoring_dominance: str | None
    lesions: list[LesionResult]
    diffuse_points: float = 0.0
