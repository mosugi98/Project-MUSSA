"""Small builders for fully answered, valid scoring cases."""
from cagsyntax.scoring.model import Case, Lesion


def lesion(**kw) -> Lesion:
    """Non-occlusive lesion on segment 8 with every applicable question answered 'no'."""
    base = dict(segments=["8"], occlusion=False, trifurcation=0, bifurcation="none",
                severe_tortuosity=False, length_gt20=False, heavy_calcification=False,
                thrombus=False)
    base.update(kw)
    return Lesion(**base)


def occluded(**kw) -> Lesion:
    """Total occlusion of segments 2+3 (first segment 2), small-side-branch path: trifurcation and
    bifurcation are not asked (None). Pass side_branch="large" plus trifurcation=0, bifurcation="none"."""
    base = dict(segments=["2", "3"], occlusion=True, first_segment="2", age_over_3_months="no",
                blunt_stump=False, bridging=False, beyond_first_visualized="none",
                side_branch="no", length_gt20=None, trifurcation=None, bifurcation=None)
    base.update(kw)
    return lesion(**base)


def case(*lesions, dominance="right", scoring=None, diffuse=()) -> Case:
    return Case(dominance=dominance, scoring_dominance=scoring, lesions=list(lesions),
                diffuse_segments=list(diffuse))
