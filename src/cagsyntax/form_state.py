"""Rules for the scoring form: which questions apply, keeping answers consistent, JSON.

Qt-free. The engine (cagsyntax.scoring) decides what a valid case is; this module mirrors its
"asked / skipped" rules so a form can enable the right controls and clear answers that stop
applying (a stale answer would otherwise make the case invalid without the scorer seeing why).
"""
from __future__ import annotations

import dataclasses
import json

from .scoring import Case, Lesion
from .scoring.tables import MEDINA, OSTIAL_SEGMENTS, SEGMENT_IDS, weight
from .scoring.validate import beyond_asked, beyond_options, tri_bif_asked

ALWAYS = {"occlusion", "severe_tortuosity", "heavy_calcification", "thrombus"}
OPTIONAL = ("first_segment", "age_over_3_months", "blunt_stump", "bridging", "beyond_first_visualized",
            "side_branch", "trifurcation", "bifurcation", "bifurcation_angle_lt70", "aorto_ostial",
            "length_gt20")


def applicable_questions(lesion: Lesion, dominance: str | None) -> set[str]:
    """Names of the lesion fields that currently apply. `dominance` is the scoring dominance
    ("right" or "left"), or None when it is not known yet."""
    qs = set(ALWAYS)
    if lesion.occlusion is True:
        qs |= {"first_segment", "age_over_3_months", "blunt_stump", "bridging", "side_branch"}
        main = lesion.first_segment
        if dominance and main in lesion.segments and main in SEGMENT_IDS and beyond_asked(main, dominance):
            qs.add("beyond_first_visualized")
    if lesion.occlusion is False:
        qs.add("length_gt20")
    if tri_bif_asked(lesion):
        qs.add("trifurcation")
        if not (isinstance(lesion.trifurcation, int) and lesion.trifurcation > 0):
            qs.add("bifurcation")
            if lesion.bifurcation in MEDINA:
                qs.add("bifurcation_angle_lt70")
    if any(s in OSTIAL_SEGMENTS for s in lesion.segments):
        qs.add("aorto_ostial")
    return qs


def clean_lesion(lesion: Lesion, dominance: str | None) -> Lesion:
    """Copy of the lesion with every answer that no longer applies set back to None."""
    les = dataclasses.replace(lesion)
    if les.first_segment is not None and les.first_segment not in les.segments:
        les.first_segment = None
    if (les.beyond_first_visualized is not None and dominance and les.first_segment in les.segments
            and les.first_segment in SEGMENT_IDS
            and les.beyond_first_visualized not in beyond_options(les.first_segment, dominance)):
        les.beyond_first_visualized = None
    # Clearing can switch other questions off, so repeat until nothing changes.
    for _ in range(len(OPTIONAL)):
        applicable = applicable_questions(les, dominance)
        stale = [f for f in OPTIONAL if f not in applicable and getattr(les, f) is not None]
        if not stale:
            break
        for f in stale:
            setattr(les, f, None)
    return les


def _scoring_dominance(dominance: str | None, scoring_dominance: str | None) -> str | None:
    return dominance if dominance in ("right", "left") else scoring_dominance


def change_dominance(case: Case, dominance: str | None, scoring_dominance: str | None) -> Case:
    """Copy of the case with new dominance. Segments that do not exist for the scoring dominance
    are removed (see removed_segments) and every lesion is cleaned."""
    dom = _scoring_dominance(dominance, scoring_dominance)
    keep = (lambda s: True) if dom not in ("right", "left") else (lambda s: weight(s, dom) is not None)
    lesions = []
    for les in case.lesions:
        les = dataclasses.replace(les, segments=[s for s in les.segments if keep(s)])
        lesions.append(clean_lesion(les, dom))
    return Case(dominance=dominance,
                scoring_dominance=scoring_dominance if dominance == "co-dominant" else None,
                lesions=lesions, diffuse_segments=[s for s in case.diffuse_segments if keep(s)])


def removed_segments(before: Case, after: Case) -> list[str]:
    """Segments present in `before` (lesions or diffuse list) but missing from `after`, in order."""
    gone: list[str] = []
    pairs = [(b.segments, a.segments) for b, a in zip(before.lesions, after.lesions)]
    pairs.append((before.diffuse_segments, after.diffuse_segments))
    for old, new in pairs:
        for s in old:
            if s not in new and s not in gone:
                gone.append(s)
    return gone


def case_to_json(case: Case) -> str:
    return json.dumps(dataclasses.asdict(case))


def case_from_json(text: str) -> Case:
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise TypeError("not an object")
        return Case.from_dict(data)
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Not a valid saved score: {exc}") from exc
