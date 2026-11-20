from __future__ import annotations

from .model import Case, CaseResult, Lesion, LesionResult, Part
from .tables import MEDINA, SEGMENT_IDS, VISUALIZED_HELP, weight
from .validate import beyond_asked, validate


def group_for(total: float) -> str:
    """Risk group. Cut-offs are the published SYNTAX groups (low <=22, intermediate 23-32,
    high >=33). A fractional total between cut-offs (22.5, 32.5) is intermediate."""
    if total <= 22:
        return "low"
    if total >= 33:
        return "high"
    return "intermediate"


def _to5_points(dominance: str, active: str) -> int:
    """Official calculateQ4V_TO5: occlusion starting in the left main (segment 5)."""
    table = {"7": 1, "8": 2, "13": 1, "14": 2}
    if dominance == "left":
        table = {**table, "15": 3, "none": 4}
    else:
        table = {**table, "none": 3}
    return table.get(active, 0)


def visualized_points(dominance: str, main_segment: str, first_visualized: str) -> int:
    """Points for the first segment beyond the occlusion that is visualized by contrast.

    Ported from the official setVisualizedByContrast: walk the segments from the occlusion's
    main segment, skipping those denied or not applicable to the dominance; each segment passed
    before the first visualized one adds a point (the first walked segment is not counted), with
    special cases checked in the official order.
    """
    start, end, denied = VISUALIZED_HELP[main_segment]
    active = first_visualized
    score = -1
    for idx in range(start, end + 1):
        number = SEGMENT_IDS[idx]
        if weight(number, dominance) is None or number in denied:
            continue
        if main_segment == "5":
            return _to5_points(dominance, active)
        if active == "16" and number == "1":
            score = 2
        elif active == "none" and number == "1" and dominance == "right":
            score = 3
        elif active == "4" and number == "1":
            score = 2
        elif active == "none" and number == "2" and dominance == "right":
            score = 2
        elif active == "16" and number == "2":
            score = 1
        elif active == "4" and number == "2":
            score = 1
        elif active == "16" and number == "3":
            score = 0
        elif active == "none" and number == "3":
            score = 1
        elif active == "16" and number == "4":
            score = 0
        elif active == "4" and number == "4":
            score = 0
        elif active == "none" and number == "4":
            score = 0
        elif number != active:
            score += 1
            continue
        break
    return max(score, 0)


def _occlusion_parts(les: Lesion, dominance: str) -> list[Part]:
    main = les.first_segment
    seg = sum(weight(s, dominance) * (5 if s == main else 2) for s in les.segments)
    parts = [Part("Segments (total occlusion: first segment x5, others x2)", seg)]
    if les.age_over_3_months in ("yes", "unknown"):
        parts.append(Part("Age of occlusion over 3 months or unknown", 1))
    if les.blunt_stump is True:
        parts.append(Part("Blunt stump", 1))
    if les.bridging is True:
        parts.append(Part("Bridging collaterals", 1))
    if beyond_asked(main, dominance):
        beyond = visualized_points(dominance, main, les.beyond_first_visualized)
        if beyond:
            parts.append(Part("Segments not visualized beyond the occlusion", beyond))
    if les.side_branch not in (None, "no"):
        parts.append(Part("Side branch at the origin of the occlusion", 1))
    return parts


def _lesion_parts(les: Lesion, dominance: str) -> list[Part]:
    parts: list[Part] = []
    if les.occlusion is True:
        parts += _occlusion_parts(les, dominance)
    else:
        seg = sum(weight(s, dominance) * 2 for s in les.segments)
        parts.append(Part("Segments (stenosis 50% or more: weight x2)", seg))
    if les.trifurcation:
        parts.append(Part(f"Trifurcation ({les.trifurcation} diseased segment"
                          f"{'s' if les.trifurcation > 1 else ''})", les.trifurcation + 2))
    elif les.bifurcation in MEDINA:
        m = MEDINA[les.bifurcation]
        parts.append(Part(f"Bifurcation (Medina {m[0]},{m[1]},{m[2]})", m[3]))
        if les.bifurcation_angle_lt70 is True:
            parts.append(Part("Bifurcation angle under 70 degrees", 1))
    if les.aorto_ostial is True:
        parts.append(Part("Aorto-ostial lesion", 1))
    if les.severe_tortuosity is True:
        parts.append(Part("Severe tortuosity", 2))
    if les.length_gt20 is True and les.occlusion is not True:
        parts.append(Part("Length over 20 mm", 1))
    if les.heavy_calcification is True:
        parts.append(Part("Heavy calcification", 2))
    if les.thrombus is True:
        parts.append(Part("Thrombus", 1))
    return parts


def score_case(case: Case) -> CaseResult:
    """Score a case. Invalid or incomplete cases return no total (see CaseResult.status)."""
    errors, missing = validate(case)
    dom = case.dominance if case.dominance in ("right", "left") else case.scoring_dominance
    if errors or missing:
        return CaseResult(status="invalid" if errors else "incomplete", issues=errors + missing,
                          total=None, group=None, dominance=case.dominance,
                          scoring_dominance=dom, lesions=[])
    results = []
    for les in case.lesions:
        parts = _lesion_parts(les, dom)
        results.append(LesionResult(total=sum(p.points for p in parts), parts=parts))
    diffuse = float(len(case.diffuse_segments))
    total = sum(r.total for r in results) + diffuse
    return CaseResult(status="complete", issues=[], total=total, group=group_for(total),
                      dominance=case.dominance, scoring_dominance=dom, lesions=results,
                      diffuse_points=diffuse)
