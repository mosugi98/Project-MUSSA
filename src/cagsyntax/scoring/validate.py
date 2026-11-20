from __future__ import annotations

from .model import Case, Issue, Lesion
from .tables import MEDINA, OSTIAL_SEGMENTS, SEGMENT_IDS, VISUALIZED_HELP, weight

MAX_LESIONS = 12  # the official calculator stops at 12
AGE = {"no", "yes", "unknown"}
SIDE = {"no", "small", "large", "both"}


def beyond_candidates(main_segment: str, dominance: str) -> list[str]:
    """Segments the official form lists for 'first segment beyond the occlusion' (without 'none'):
    those in the main segment's range that are not denied and apply to the dominance."""
    start, end, denied = VISUALIZED_HELP[main_segment]
    return [s for s in SEGMENT_IDS[start:end + 1] if s not in denied and weight(s, dominance) is not None]


def beyond_asked(main_segment: str, dominance: str) -> bool:
    """The official form skips the question when at most one candidate remains."""
    return len(beyond_candidates(main_segment, dominance)) > 1


def beyond_options(main_segment: str, dominance: str) -> set[str]:
    return set(beyond_candidates(main_segment, dominance)) | {"none"}


def tri_bif_asked(les: Lesion) -> bool | None:
    """Trifurcation and bifurcation are asked unless a total occlusion has a side branch under
    1.5 mm or none. None means 'cannot tell yet' (occlusion with an unanswered side branch)."""
    if les.occlusion is not True:
        return True
    if les.side_branch is None:
        return None
    return les.side_branch in ("large", "both")


def _scoring_dominance(case: Case, errors: list[Issue], missing: list[Issue]) -> str | None:
    d, s = case.dominance, case.scoring_dominance
    if d is None:
        missing.append(Issue("no_dominance", "Choose the coronary dominance."))
        return None
    if d in ("right", "left"):
        if s not in (None, d):
            errors.append(Issue("dominance_mismatch",
                                f"Scoring dominance {s!r} does not match {d} dominance."))
        return d
    if d == "co-dominant":
        if s in ("right", "left"):
            return s
        if s is None:
            missing.append(Issue("no_scoring_dominance",
                                 "Co-dominant: choose right or left as the scoring table."))
        else:
            errors.append(Issue("invalid_scoring_dominance", f"Unknown scoring dominance {s!r}."))
        return None
    errors.append(Issue("invalid_dominance", f"Unknown dominance {d!r}."))
    return None


def _validate_occlusion(les: Lesion, segs: list[str], dom: str | None, err, miss) -> None:
    first = les.first_segment
    if first is None:
        miss("occlusion_incomplete", "Mark the first segment of the total occlusion.")
    elif first not in segs:
        err("first_segment_not_in_lesion", f"First occlusion segment {first} is not in the lesion.")
    answers = (les.age_over_3_months, les.blunt_stump, les.bridging, les.side_branch)
    if any(v is None for v in answers):
        miss("occlusion_incomplete", "Answer all total occlusion questions.")
    if les.age_over_3_months is not None and les.age_over_3_months not in AGE:
        err("invalid_age", f"Unknown occlusion age {les.age_over_3_months!r}.")
    if les.side_branch is not None and les.side_branch not in SIDE:
        err("invalid_side_branch", f"Unknown side branch answer {les.side_branch!r}.")
    if dom and first in SEGMENT_IDS and first in segs:
        if beyond_asked(first, dom):
            if les.beyond_first_visualized is None:
                miss("occlusion_incomplete", "Answer the first segment visualized beyond the occlusion.")
            elif les.beyond_first_visualized not in beyond_options(first, dom):
                err("beyond_segment_invalid",
                    f"Segment {les.beyond_first_visualized!r} cannot be the first visualized "
                    f"segment beyond this occlusion.")
        elif les.beyond_first_visualized is not None:
            err("beyond_not_asked", "The first-visualized-segment question does not apply to this occlusion.")
    if les.length_gt20:
        err("length_with_occlusion", "Length >20 mm is not asked for a total occlusion.")


def _validate_lesion(i: int, les: Lesion, dom: str | None, errors: list[Issue],
                     missing: list[Issue]) -> None:
    def err(code, msg):
        errors.append(Issue(code, msg, i))

    def miss(code, msg):
        missing.append(Issue(code, msg, i))

    if not isinstance(les.segments, (list, tuple)):
        err("bad_input", "segments must be a list")
        return
    if not les.segments:
        miss("no_segments", "Select at least one diseased segment.")
        return
    segs = list(les.segments)
    for s in segs:
        if s not in SEGMENT_IDS:
            err("unknown_segment", f"Unknown segment {s!r}.")
        elif dom and weight(s, dom) is None:
            err("segment_not_applicable", f"Segment {s} does not exist for {dom} dominance.")
    if len(set(segs)) != len(segs):
        err("duplicate_segment", "A segment is selected twice.")

    if les.occlusion is True:
        _validate_occlusion(les, segs, dom, err, miss)
    else:
        occ_fields = (les.first_segment, les.age_over_3_months, les.blunt_stump, les.bridging,
                      les.beyond_first_visualized, les.side_branch)
        if any(v is not None for v in occ_fields):
            err("occlusion_fields_without_occlusion", "Occlusion answers given without an occlusion.")
        if les.occlusion is None:
            miss("question_unanswered", "Answer: total occlusion?")
        elif les.length_gt20 is None:
            miss("question_unanswered", "Answer: length over 20 mm?")

    tri, bif = les.trifurcation, les.bifurcation
    asked = tri_bif_asked(les)
    if asked is False:
        if tri is not None or bif is not None or les.bifurcation_angle_lt70 is not None:
            err("trifurcation_bifurcation_not_asked",
                "Trifurcation and bifurcation are only asked after an occlusion with a side branch "
                "of 1.5 mm or more.")
    elif asked:
        if tri is None:
            miss("question_unanswered", "Answer: trifurcation?")
        elif tri not in (0, 1, 2, 3, 4):
            err("invalid_trifurcation", f"Trifurcation must be 0 to 4, got {tri!r}.")
        if bif is None:
            miss("question_unanswered", "Answer: bifurcation?")
        elif bif != "none" and bif not in MEDINA:
            err("invalid_bifurcation", f"Unknown bifurcation type {bif!r}.")
        if isinstance(tri, int) and tri > 0 and bif not in (None, "none"):
            err("trifurcation_and_bifurcation", "A lesion cannot have both a trifurcation and a bifurcation.")
        if bif in MEDINA and les.bifurcation_angle_lt70 is None:
            miss("question_unanswered", "Answer: bifurcation angle under 70 degrees?")
        if les.bifurcation_angle_lt70 and bif in (None, "none"):
            err("angle_without_bifurcation", "Bifurcation angle given without a bifurcation.")

    if any(s in OSTIAL_SEGMENTS for s in segs):
        if les.aorto_ostial is None:
            miss("question_unanswered", "Answer: aorto-ostial lesion?")
    elif les.aorto_ostial:
        err("ostial_not_applicable", "Aorto-ostial applies only to segments 1, 5, 6 and 11.")

    for name, label in (("severe_tortuosity", "severe tortuosity"),
                        ("heavy_calcification", "heavy calcification"), ("thrombus", "thrombus")):
        if getattr(les, name) is None:
            miss("question_unanswered", f"Answer: {label}?")


def validate(case: Case) -> tuple[list[Issue], list[Issue]]:
    """Return (errors, missing). Errors make a case invalid; missing items make it incomplete."""
    errors: list[Issue] = []
    missing: list[Issue] = []
    dom = _scoring_dominance(case, errors, missing)
    lesions = case.lesions if isinstance(case.lesions, (list, tuple)) else []
    if not isinstance(case.lesions, (list, tuple)):
        errors.append(Issue("bad_input", "lesions must be a list"))
    elif not lesions:
        missing.append(Issue("no_lesions", "Add at least one lesion."))
    if len(lesions) > MAX_LESIONS:
        errors.append(Issue("too_many_lesions", f"At most {MAX_LESIONS} lesions are allowed."))
    for i, les in enumerate(lesions):
        _validate_lesion(i, les, dom, errors, missing)
    diffuse = case.diffuse_segments
    if not isinstance(diffuse, (list, tuple)):
        errors.append(Issue("bad_input", "diffuse_segments must be a list"))
    else:
        for s in diffuse:
            if s not in SEGMENT_IDS or (dom and weight(s, dom) is None):
                errors.append(Issue("diffuse_segment_not_applicable",
                                    f"Diffuse disease segment {s!r} does not apply."))
    return errors, missing
