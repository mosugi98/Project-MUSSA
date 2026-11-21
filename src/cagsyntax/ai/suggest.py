"""Turn stenosis candidates and segment masks into suggestions for the scoring form.

Everything here is a suggestion for the scorer to accept or reject. A suggestion fills in nothing but the
segment of a lesion; dominance and every clinical-judgement answer stay for the scorer."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..scoring import Lesion
from .segment_names import SEGMENT_NAMES
from .stenosis import Candidate

DEFAULT_MIN_OVERLAP = 0.2


@dataclass
class Suggestion:
    segment: str | None         # None: the candidate lies outside every outlined segment ("unplaced")
    score: float                # the stenosis model's confidence in this candidate, 0 to 1
    pixels: int                 # size of the candidate
    overlap: float              # share of the candidate that lies inside `segment`, 0 to 1
    box: tuple                  # (x0, y0, x1, y1), x1 and y1 exclusive


def suggest(candidates: list[Candidate], segment_masks: np.ndarray,
            min_overlap: float = DEFAULT_MIN_OVERLAP) -> list[Suggestion]:
    """Place each candidate in the segment that covers most of it. Below `min_overlap` the candidate is
    reported as unplaced rather than dropped. Ties go to the segment that comes first in table order.
    Best score first."""
    masks = np.asarray(segment_masks, dtype=bool)
    if masks.ndim != 3 or masks.shape[0] != len(SEGMENT_NAMES):
        raise ValueError(f"segment_masks must have shape ({len(SEGMENT_NAMES)}, H, W), got {masks.shape}")
    out: list[Suggestion] = []
    for c in candidates:
        if c.mask.shape != masks.shape[1:]:
            raise ValueError(f"A candidate mask of shape {c.mask.shape} does not fit segment masks of {masks.shape[1:]}.")
        inside = (masks & c.mask[None]).sum(axis=(1, 2))
        best = int(np.argmax(inside))                               # first maximum = table order
        overlap = float(inside[best]) / c.pixels if c.pixels else 0.0
        placed = inside[best] > 0 and overlap >= min_overlap
        out.append(Suggestion(segment=SEGMENT_NAMES[best] if placed else None, score=c.score, pixels=c.pixels,
                              overlap=overlap if inside[best] > 0 else 0.0, box=c.box))
    return sorted(out, key=lambda s: -s.score)


def lesions_from(suggestions: list[Suggestion]) -> list[Lesion]:
    """One lesion per distinct placed segment, in order of first appearance. Only `segments` is set."""
    seen: list[str] = []
    for s in suggestions:
        if s.segment is not None and s.segment not in seen:
            seen.append(s.segment)
    return [Lesion(segments=[segment]) for segment in seen]
