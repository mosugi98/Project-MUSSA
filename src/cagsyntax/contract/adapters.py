"""Convert between the engine's own types and the contract, in both directions.

The engine (`cagsyntax.scoring`) and the suggestion code (`cagsyntax.ai.suggest`) keep their plain dataclasses;
nothing in them changes. These functions copy: the result never shares a list with its source, and a value the
contract does not know is refused (pydantic raises a ValidationError, which is a ValueError)."""
from __future__ import annotations

import dataclasses

from ..ai.suggest import Suggestion
from ..scoring import VERSION, Case, CaseResult, Lesion
from .models import (CaseForm, Evidence, Finding, IssueRecord, LesionForm, LesionProposal, ModelRef, ScoreSummary)


# ---------------------------------------------------------------- the scoring form
def lesion_to_form(lesion: Lesion) -> LesionForm:
    return LesionForm(**dataclasses.asdict(lesion))


def form_to_lesion(form: LesionForm) -> Lesion:
    return Lesion(**form.model_dump())


def case_to_form(case: Case) -> CaseForm:
    return CaseForm(dominance=case.dominance, scoring_dominance=case.scoring_dominance,
                    lesions=[lesion_to_form(les) for les in case.lesions],
                    diffuse_segments=list(case.diffuse_segments))


def form_to_case(form: CaseForm) -> Case:
    return Case(dominance=form.dominance, scoring_dominance=form.scoring_dominance,
                lesions=[form_to_lesion(les) for les in form.lesions],
                diffuse_segments=list(form.diffuse_segments))


# ---------------------------------------------------------------- the engine's answer
def score_to_summary(result: CaseResult) -> ScoreSummary:
    """A read-only snapshot of the engine's result, stamped with the engine version."""
    return ScoreSummary(status=result.status, total=result.total, group=result.group, engine_version=VERSION,
                        issues=[IssueRecord(code=i.code, message=i.message, lesion=i.lesion) for i in result.issues],
                        lesion_totals=[les.total for les in result.lesions], diffuse_points=result.diffuse_points)


# ---------------------------------------------------------------- suggestions
def finding_from_suggestion(suggestion: Suggestion, series_uid: str, frame: int, primary_angle: float | None,
                            secondary_angle: float | None, models: list[ModelRef]) -> Finding:
    """A suggestion plus where it was seen (series, frame, C-arm angles) and which models produced it."""
    return Finding(evidence=Evidence(series_uid=series_uid, frame=frame, primary_angle=primary_angle,
                                     secondary_angle=secondary_angle,
                                     box=tuple(int(v) for v in suggestion.box) if suggestion.box is not None else None),
                   segment=suggestion.segment, score=float(suggestion.score), pixels=int(suggestion.pixels),
                   overlap=float(suggestion.overlap), models=list(models))


def proposals_from_findings(findings: list[Finding]) -> list[LesionProposal]:
    """One AI proposal per distinct placed segment, in order of first appearance, citing its findings. The lesion
    form has the segment and nothing else: every clinical answer stays for the scorer."""
    grouped: dict[str, list[Finding]] = {}
    for f in findings:
        if f.segment is not None:
            grouped.setdefault(f.segment, []).append(f)
    return [LesionProposal(form=LesionForm(segments=[segment]), findings=found, source="ai")
            for segment, found in grouped.items()]
