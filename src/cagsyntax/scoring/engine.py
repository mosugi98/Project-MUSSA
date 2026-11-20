from __future__ import annotations

from .model import Case, CaseResult, Lesion, LesionResult, Part
from .tables import MEDINA, weight
from .validate import validate


def group_for(total: float) -> str:
    """Risk group. Cut-offs are the published SYNTAX groups (low <=22, intermediate 23-32,
    high >=33); a fractional total such as 22.5 falls in the next group up."""
    if total <= 22:
        return "low"
    if total >= 33:
        return "high"
    return "intermediate"


def _occlusion_parts(les: Lesion, dominance: str) -> list[Part]:
    raise NotImplementedError("total occlusion is added in plan task 4")


def _lesion_parts(les: Lesion, dominance: str) -> list[Part]:
    parts: list[Part] = []
    if les.occlusion:
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
        if les.bifurcation_angle_lt70:
            parts.append(Part("Bifurcation angle under 70 degrees", 1))
    if les.aorto_ostial:
        parts.append(Part("Aorto-ostial lesion", 1))
    if les.severe_tortuosity:
        parts.append(Part("Severe tortuosity", 2))
    if les.length_gt20 and not les.occlusion:
        parts.append(Part("Length over 20 mm", 1))
    if les.heavy_calcification:
        parts.append(Part("Heavy calcification", 2))
    if les.thrombus:
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
