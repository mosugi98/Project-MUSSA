import numpy as np
import pytest

from cagsyntax.ai.segment_names import SEGMENT_NAMES
from cagsyntax.ai.stenosis import Candidate
from cagsyntax.ai.suggest import Suggestion, lesions_from, suggest
from cagsyntax.scoring import Lesion

H = W = 40


def seg_masks(**regions):
    """25-channel mask with a rectangle (y0, y1, x0, x1) per named segment."""
    m = np.zeros((25, H, W), dtype=bool)
    for name, (y0, y1, x0, x1) in regions.items():
        m[SEGMENT_NAMES.index(name), y0:y1, x0:x1] = True
    return m


def cand(y0, y1, x0, x1, score=0.8):
    mask = np.zeros((H, W), dtype=bool)
    mask[y0:y1, x0:x1] = True
    return Candidate(mask=mask, box=(x0, y0, x1, y1), pixels=int(mask.sum()), score=score)


def test_a_candidate_is_placed_in_the_segment_it_overlaps_most():
    masks = seg_masks(**{"6": (0, 20, 0, 40), "7": (20, 40, 0, 40)})
    out = suggest([cand(14, 22, 5, 10)], masks)                # 6 rows in 6, 2 rows in 7
    assert len(out) == 1 and isinstance(out[0], Suggestion)
    assert out[0].segment == "6" and out[0].overlap == pytest.approx(30 / 40)
    assert out[0].score == 0.8 and out[0].pixels == 40 and out[0].box == (5, 14, 10, 22)


def test_a_candidate_outside_every_segment_is_unplaced_not_dropped():
    out = suggest([cand(30, 35, 30, 35)], seg_masks(**{"6": (0, 10, 0, 10)}))
    assert len(out) == 1 and out[0].segment is None and out[0].overlap == 0.0


def test_a_candidate_with_too_little_overlap_is_unplaced():
    masks = seg_masks(**{"6": (0, 10, 0, 10)})
    barely = cand(8, 18, 0, 10)                                # 2 of 10 rows inside = 20%
    assert suggest([barely], masks, min_overlap=0.3)[0].segment is None
    assert suggest([barely], masks, min_overlap=0.2)[0].segment == "6"


def test_ties_go_to_the_segment_that_comes_first_in_table_order():
    masks = seg_masks(**{"7": (0, 10, 0, 10), "6": (0, 10, 0, 10)})        # the same area, named in reverse order
    assert suggest([cand(0, 10, 0, 10)], masks)[0].segment == "6"


def test_several_candidates_in_one_segment_are_kept_separately_best_first():
    masks = seg_masks(**{"6": (0, 40, 0, 40)})
    out = suggest([cand(0, 5, 0, 5, score=0.6), cand(10, 15, 10, 15, score=0.9)], masks)
    assert [s.score for s in out] == [0.9, 0.6] and {s.segment for s in out} == {"6"}


def test_no_candidates_gives_no_suggestions():
    assert suggest([], seg_masks(**{"6": (0, 10, 0, 10)})) == []


def test_mismatched_shapes_are_refused():
    with pytest.raises(ValueError):
        suggest([cand(0, 5, 0, 5)], np.zeros((25, 10, 10), dtype=bool))
    with pytest.raises(ValueError):
        suggest([cand(0, 5, 0, 5)], np.zeros((3, H, W), dtype=bool))


def test_lesions_from_makes_one_segments_only_lesion_per_placed_segment():
    sugg = [Suggestion("6", 0.9, 10, 1.0, (0, 0, 1, 1)), Suggestion("6", 0.6, 8, 0.9, (0, 0, 1, 1)),
            Suggestion("11", 0.7, 9, 0.8, (0, 0, 1, 1)), Suggestion(None, 0.95, 12, 0.0, (0, 0, 1, 1))]
    lesions = lesions_from(sugg)
    assert [les.segments for les in lesions] == [["6"], ["11"]] and all(isinstance(les, Lesion) for les in lesions)
    les = lesions[0]
    assert les.occlusion is None and les.trifurcation is None and les.bifurcation is None
    assert les.thrombus is None and les.length_gt20 is None and les.heavy_calcification is None


def test_lesions_from_nothing_is_empty():
    assert lesions_from([]) == []
    assert lesions_from([Suggestion(None, 0.9, 1, 0.0, (0, 0, 1, 1))]) == []
