"""Turn the agent layer's types into the engine's own `Case`, and its result into a `StudySyntaxOutput`.

The SYNTAX score is only ever computed by `cagsyntax.scoring.score_case`. Nothing here adds up points.
Where the draft's data model and the official form differ, the official form wins and the difference is
explained in `schema.py`."""
from __future__ import annotations

from ..form_state import applicable_questions
from ..scoring import VERSION, Case, Lesion, score_case
from ..scoring.tables import MEDINA, SEGMENT_IDS
from .schema import (IssueItem, LesionBreakdown, LesionInput, PartRecord, StudySyntaxInput, StudySyntaxOutput)

# "1,1,0" -> "C": the engine names Medina types by letter
MEDINA_LETTER = {f"{m[0]},{m[1]},{m[2]}": letter for letter, m in MEDINA.items()}
SIDE_BRANCH = {"none": "no", "sb_lt_1_5mm": "small", "sb_ge_1_5mm": "large", "both_sb": "both"}

# answers that mean "no": dropped when the question does not apply to the lesion, so a default False never
# turns into an "invalid" case. A "yes" on a question that does not apply is kept: the engine must report it.
_NEGATIVE = (False, 0, "none", "no")
_QUESTIONS = ("aorto_ostial", "bifurcation", "trifurcation", "heavy_calcification", "length_gt20", "severe_tortuosity",
              "thrombus", "age_over_3_months", "blunt_stump", "bridging", "side_branch")


class AdapterError(ValueError):
    """The agent layer's data cannot be expressed in the official SYNTAX form. The message says how to fix it."""


def _engine_dominance(dominance: str, scoring_dominance: str | None) -> str | None:
    return dominance if dominance in ("right", "left") else scoring_dominance


def lesion_input_to_lesion(item: LesionInput, dominance: str | None) -> Lesion:
    """`dominance` is the scoring dominance ("right"/"left") or None when it is not known yet."""
    segments = [s for s in SEGMENT_IDS if s in {x.segment_id for x in item.involved_segments}]
    if item.draft:
        return Lesion(segments=segments)                                   # the segment, and nothing else
    occluded = [x.segment_id for x in item.involved_segments if x.is_total_occlusion]
    if len(occluded) > 1:
        raise AdapterError(
            f"Lesion '{item.lesion_id}' marks {len(occluded)} segments as occluded. In the official SYNTAX score "
            "only the first segment of a total occlusion counts x5 and the other segments of the lesion count x2: "
            "mark only the first segment as occluded and list the others as ordinary segments of the lesion.")
    les = Lesion(segments=segments, aorto_ostial=item.is_aorto_ostial, severe_tortuosity=item.has_severe_tortuosity,
                 length_gt20=item.length_gt_20mm, heavy_calcification=item.has_heavy_calcification,
                 thrombus=item.has_thrombus)
    if occluded:
        les.occlusion, les.first_segment = True, occluded[0]
        details = item.total_occlusion_details
        if details is not None:
            les.age_over_3_months = "yes" if details.age_gt_3_months_or_unknown else "no"
            les.blunt_stump, les.bridging = details.blunt_stump, details.bridging_collaterals
            les.beyond_first_visualized = details.first_visualized_beyond
            les.side_branch = SIDE_BRANCH[details.side_branch_involvement]
    else:
        les.occlusion = False
    if item.bifurcation is not None:
        les.bifurcation = MEDINA_LETTER[item.bifurcation.medina]
        les.bifurcation_angle_lt70 = item.bifurcation.angulation_lt_70_deg
        les.trifurcation = 0
    elif item.trifurcation is not None:
        les.trifurcation, les.bifurcation = item.trifurcation.diseased_segments_count, "none"
    else:
        les.trifurcation, les.bifurcation = 0, "none"
    if dominance is not None:
        applicable = applicable_questions(les, dominance)
        for question in _QUESTIONS:
            if question not in applicable and getattr(les, question) in _NEGATIVE:
                setattr(les, question, None)
    if les.bifurcation not in MEDINA:
        les.bifurcation_angle_lt70 = None
    return les


def study_to_case(study: StudySyntaxInput) -> Case:
    scoring = study.scoring_dominance if study.dominance == "co-dominant" else None
    dom = _engine_dominance(study.dominance, scoring)
    diffuse = [s for s in SEGMENT_IDS if s in set(study.diffuse_disease_segments)]
    return Case(dominance=study.dominance, scoring_dominance=scoring,
                lesions=[lesion_input_to_lesion(item, dom) for item in study.lesions], diffuse_segments=diffuse)


def score_study(study: StudySyntaxInput) -> StudySyntaxOutput:
    """Score a study with the project's engine. The total is None unless the case is complete."""
    case = study_to_case(study)
    result = score_case(case)
    ids = [item.lesion_id for item in study.lesions]
    issues = [IssueItem(code=i.code, message=i.message,
                        lesion_id=ids[i.lesion] if i.lesion is not None and i.lesion < len(ids) else None)
              for i in result.issues]
    breakdowns = [LesionBreakdown(lesion_id=ids[n], parts=[PartRecord(label=p.label, points=float(p.points))
                                                           for p in les.parts],
                                  lesion_total_score=float(les.total))
                  for n, les in enumerate(result.lesions)]
    flagged = any(item.primary_evidence is not None and item.primary_evidence.needs_attention for item in study.lesions)
    return StudySyntaxOutput(study_instance_uid=study.study_instance_uid, dominance=study.dominance,
                             status=result.status, issues=issues, lesion_breakdowns=breakdowns,
                             diffuse_disease_score=float(result.diffuse_points),
                             total_syntax_score=None if result.total is None else float(result.total),
                             risk_category=result.group,
                             requires_physician_attention=flagged or result.status != "complete",
                             engine_version=VERSION)
