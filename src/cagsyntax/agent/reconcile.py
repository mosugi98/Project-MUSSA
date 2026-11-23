"""Reconcile what the vision models saw in the different runs of one study into proposed lesions.

Deterministic and explainable: the same input in any order gives the same output, and every decision is written
down. The result is a set of DRAFT lesions (one per segment) with a primary view, supporting views and reasons for
the physician's attention. It never decides dominance by guessing, never answers a clinical question, never drops a
candidate silently (candidates outside every segment are reported), and never mixes two studies.

Not done here, because nothing can measure it yet: foreshortening (the primary view is the highest model score, then
the best placement), vessel diameter (so two narrowings in one segment are flagged, not split), and continuity of a
lesion across neighbouring segments (the scorer joins lesions)."""
from __future__ import annotations

from typing import Protocol

from pydantic import Field

from ..ai.segment_names import SEGMENT_NAMES
from ..contract.models import ContractModel
from .schema import (Dominance, InvolvedSegment, LesionInput, RawCVLesionCandidate, RunPerceptionSummary,
                     StudySyntaxInput, ViewEvidence)

LOW_SCORE = 0.80                     # a model score under this asks for the physician's attention
SCORE_SPREAD = 0.30                  # views whose scores differ by this much or more disagree
MIN_PLACEMENT = 0.50                 # a candidate mostly outside its segment is only loosely placed
OVERLAP_PRONE_SEGMENTS = ("5", "6", "11")      # LM, proximal LAD, proximal LCx: vessels overlap here


class ReconcileError(ValueError):
    """The runs cannot be reconciled. The message is meant to be shown to a person."""


class MergeNote(ContractModel):
    lesion_id: str
    segment: str
    primary_candidate_id: str
    supporting_candidate_ids: list[str] = Field(default_factory=list)
    attention_reasons: list[str] = Field(default_factory=list)


class Reconciliation(ContractModel):
    study: StudySyntaxInput
    unplaced: list[RawCVLesionCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    merges: list[MergeNote] = Field(default_factory=list)


class Reconciler(Protocol):
    """Anything that turns the runs of a study into a Reconciliation (the deterministic one below, or later an
    optional LLM-assisted one that must return the same shape)."""
    def reconcile(self, runs: list[RunPerceptionSummary], study_instance_uid: str | None = None,
                  dominance: Dominance | None = None) -> Reconciliation: ...


def _rank(c: RawCVLesionCandidate):
    """Best first: model score, then placement, then size; the ids make ties deterministic."""
    return (-c.stenosis_score, -c.segment_overlap, -c.pixels, c.series_instance_uid, c.frame_index, c.candidate_id)


def _evidence(c: RawCVLesionCandidate, needs_attention: bool = False) -> ViewEvidence:
    return ViewEvidence(series_instance_uid=c.series_instance_uid, sop_instance_uid=c.sop_instance_uid,
                        frame_index=c.frame_index, primary_angle_deg=c.primary_angle_deg,
                        secondary_angle_deg=c.secondary_angle_deg, bbox_xyxy=c.bbox_xyxy,
                        confidence_score=c.stenosis_score, needs_attention=needs_attention)


def _apart(a: RawCVLesionCandidate, b: RawCVLesionCandidate) -> bool:
    """Two boxes in the same frame that do not touch: likely two separate narrowings."""
    if a.bbox_xyxy is None or b.bbox_xyxy is None:
        return False
    ax0, ay0, ax1, ay1 = a.bbox_xyxy
    bx0, by0, bx1, by1 = b.bbox_xyxy
    return ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0


def _study_uid(runs: list[RunPerceptionSummary], given: str | None) -> str:
    found = sorted({r.study_instance_uid for r in runs if r.study_instance_uid})
    if len(found) > 1:
        raise ReconcileError(f"The runs belong to different studies ({', '.join(found)}). Reconcile one study at a "
                             "time, so findings of one patient are never mixed into another.")
    if given is not None and found and given != found[0]:
        raise ReconcileError(f"The study uid given ({given}) contradicts the one in the runs ({found[0]}).")
    uid = given or (found[0] if found else None)
    if uid is None:
        raise ReconcileError("The study uid is unknown: the runs do not carry one and none was given.")
    return uid


def _dominance(runs: list[RunPerceptionSummary], given: Dominance | None, warnings: list[str]) -> Dominance | None:
    if given is not None:
        return given
    seen = sorted({r.pda_origin_detected for r in runs if r.pda_origin_detected})
    if len(seen) == 1:
        return seen[0]
    if len(seen) > 1:
        warnings.append("The runs disagree about the dominant coronary artery (PDA origin: "
                        f"{' vs '.join(seen)}); dominance is left for the scorer to decide.")
    return None


def reconcile(runs: list[RunPerceptionSummary], study_instance_uid: str | None = None,
              dominance: Dominance | None = None) -> Reconciliation:
    if not runs:
        raise ReconcileError("There are no runs to reconcile.")
    uid = _study_uid(runs, study_instance_uid)
    warnings: list[str] = []
    final_dominance = _dominance(runs, dominance, warnings)
    labels = {r.series_instance_uid: r.view_label for r in runs}
    unique = {c.candidate_id: c for r in runs for c in r.candidates}          # a repeated candidate counts once
    ordered = sorted(unique.values(), key=_rank)
    unplaced = [c for c in ordered if c.predicted_segment is None]
    lesions: list[LesionInput] = []
    merges: list[MergeNote] = []
    for segment in SEGMENT_NAMES:
        group = [c for c in ordered if c.predicted_segment == segment]
        if not group:
            continue
        primary, supporting = group[0], group[1:]
        reasons: list[str] = []
        if primary.stenosis_score < LOW_SCORE:
            reasons.append(f"the model score is only {primary.stenosis_score:.2f}")
        if primary.segment_overlap < MIN_PLACEMENT:
            reasons.append("the narrowing lies only partly inside the outlined segment")
        if segment in OVERLAP_PRONE_SEGMENTS:
            reasons.append(f"segment {segment} is a busy bifurcation area where vessels overlap")
        scores = [c.stenosis_score for c in group]
        if max(scores) - min(scores) >= SCORE_SPREAD:
            reasons.append(f"the views disagree strongly (model score {max(scores):.2f} in one view, "
                           f"{min(scores):.2f} in another)")
        for i, a in enumerate(group):
            if any(b.series_instance_uid == a.series_instance_uid and b.frame_index == a.frame_index and _apart(a, b)
                   for b in group[i + 1:]):
                reasons.append("two separate narrowings were found in this segment of one frame")
                warnings.append(f"Segment {segment}: two separate narrowings in one frame may be a second lesion; "
                                "check it in the viewer.")
                break
        view_ids = {c.series_instance_uid for c in group}
        views_text = ", ".join(sorted({labels.get(v, v) for v in view_ids}))
        n = len(view_ids)
        text = (f"Narrowing suggested in segment {segment}, seen in {n} view{'s' if n != 1 else ''} ({views_text}). "
                f"Best view: {labels.get(primary.series_instance_uid, primary.series_instance_uid)}, frame "
                f"{primary.frame_index}, model score {primary.stenosis_score:.2f} (a model score, not a stenosis "
                "percentage).")
        if reasons:
            text += " Please check: " + "; ".join(reasons) + "."
        text += " The AI proposes the segment only; dominance and every lesion answer are for the scorer."
        lesion_id = f"AI_{segment}"
        lesions.append(LesionInput(lesion_id=lesion_id, involved_segments=[InvolvedSegment(segment_id=segment)],
                                   primary_evidence=_evidence(primary, bool(reasons)),
                                   supporting_views=[_evidence(c) for c in supporting], agent_reasoning=text,
                                   draft=True))
        merges.append(MergeNote(lesion_id=lesion_id, segment=segment, primary_candidate_id=primary.candidate_id,
                                supporting_candidate_ids=[c.candidate_id for c in supporting],
                                attention_reasons=reasons))
    if unplaced:
        warnings.append(f"{len(unplaced)} candidate(s) lie outside the outlined segments and were not turned into "
                        "lesions; check them in the viewer.")
    if not unique:
        warnings.append("No narrowings were suggested in any run.")
    study = StudySyntaxInput(study_instance_uid=uid, dominance=final_dominance, lesions=lesions)
    return Reconciliation(study=study, unplaced=unplaced, warnings=warnings, merges=merges)


class DeterministicReconciler:
    """The rule-based reconciler as an object, so it can be swapped for an optional LLM-assisted one."""

    def reconcile(self, runs: list[RunPerceptionSummary], study_instance_uid: str | None = None,
                  dominance: Dominance | None = None) -> Reconciliation:
        return reconcile(runs, study_instance_uid, dominance)
