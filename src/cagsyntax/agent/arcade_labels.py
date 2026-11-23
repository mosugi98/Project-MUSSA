"""How the annotation dataset (ARCADE, COCO format) names and places things, and how that maps to this project.

  - Categories are matched BY NAME. ARCADE's numeric ids (1..26) follow ARCADE's own order, not the order of the
    SYNTAX tables or of the model's output channels, so an id is never used as a channel number.
  - ARCADE coordinates are pixels of the original image; a COCO bbox is [x, y, width, height]. This project's boxes
    are integer pixel (x0, y0, x1, y1) with x1 and y1 exclusive, in the frame's own size.
"""
from __future__ import annotations

import math

import numpy as np

from ..ai.segment_names import SEGMENT_NAMES

STENOSIS_CATEGORY_ID = 26

# (id, name) exactly as in arcade/<task>/<split>/annotations/<split>.json
ARCADE_CATEGORIES = [
    (1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "5"), (6, "6"), (7, "7"), (8, "8"), (9, "9"), (10, "9a"), (11, "10"),
    (12, "10a"), (13, "11"), (14, "12"), (15, "12a"), (16, "13"), (17, "14"), (18, "14a"), (19, "15"), (20, "16"),
    (21, "16a"), (22, "16b"), (23, "16c"), (24, "12b"), (25, "14b"), (26, "stenosis"),
]


def segment_for_category(name: str) -> str | None:
    """The SYNTAX segment a category name stands for, or None for the stenosis category. Stray spaces and capitals
    (common in labelling tools) are tolerated; anything else is an error, never a guess."""
    tidy = str(name).strip().lower()
    if tidy == "stenosis":
        return None
    if tidy in SEGMENT_NAMES:
        return tidy
    raise ValueError(f"{name!r} is not a SYNTAX segment name or 'stenosis'")


def xyxy_from_coco_bbox(bbox, image_size: tuple[int, int] | None = None) -> tuple[int, int, int, int]:
    """COCO [x, y, width, height] in pixels -> integer (x0, y0, x1, y1), x1 and y1 exclusive, growing outwards so the
    box always contains the original. With `image_size` = (width, height) the box is clipped to the image."""
    if len(bbox) != 4:
        raise ValueError("a COCO bbox has four numbers: x, y, width, height")
    x, y, w, h = (float(v) for v in bbox)
    if w <= 0 or h <= 0:
        raise ValueError("a bbox needs a width and a height above zero")
    x0, y0, x1, y1 = math.floor(x), math.floor(y), math.ceil(x + w), math.ceil(y + h)
    if image_size is not None:
        width, height = image_size
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(width, x1), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("the bbox lies outside the image")
    return x0, y0, x1, y1


def xyxy_from_mask(mask: np.ndarray) -> tuple[int, int, int, int]:
    """The tight (x0, y0, x1, y1) box of a boolean mask, x1 and y1 exclusive."""
    ys, xs = np.nonzero(np.asarray(mask, dtype=bool))
    if xs.size == 0:
        raise ValueError("the mask is empty")
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
