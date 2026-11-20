from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .segment_names import SEGMENT_NAMES

_CHANNEL = {name: i for i, name in enumerate(SEGMENT_NAMES)}
STENOSIS = "stenosis"          # ARCADE's 26th category; not a segment


def polygon_to_mask(polygon: list[float], height: int, width: int) -> np.ndarray:
    """Rasterise a COCO polygon (flat list x1, y1, x2, y2, ...) to a boolean (height, width) mask.
    Fewer than three points give an empty mask; points outside the image are clipped."""
    mask = Image.new("L", (width, height), 0)
    points = [(float(polygon[i]), float(polygon[i + 1])) for i in range(0, len(polygon) - 1, 2)]
    if len(points) >= 3:
        ImageDraw.Draw(mask).polygon(points, fill=1, outline=1)
    return np.asarray(mask, dtype=bool)


class ArcadeSplit:
    """One ARCADE split folder, for example arcade/arcade/syntax/train: `images/` and
    `annotations/<split>.json` in COCO format."""

    def __init__(self, root: Path):
        self.root = Path(root)
        data = json.loads((self.root / "annotations" / f"{self.root.name}.json").read_text(encoding="utf-8"))
        names = {c["id"]: c["name"] for c in data["categories"]}
        self._images = {im["id"]: im for im in data["images"]}
        self.image_ids: list[int] = sorted(self._images)
        self._annotations: dict[int, list[tuple[str, list]]] = {i: [] for i in self.image_ids}
        for ann in data["annotations"]:
            name = names[ann["category_id"]]
            if name == STENOSIS:
                continue
            if name not in _CHANNEL:
                raise ValueError(f"Unknown ARCADE category {name!r}: not one of the 25 SYNTAX segments.")
            seg = ann["segmentation"]
            if not isinstance(seg, list):
                raise ValueError(f"Annotation {ann.get('id')}: only polygon segmentations are supported.")
            self._annotations[ann["image_id"]].append((name, seg))

    def __len__(self) -> int:
        return len(self.image_ids)

    def load_image(self, i: int) -> np.ndarray:
        info = self._images[self.image_ids[i]]
        with Image.open(self.root / "images" / info["file_name"]) as im:
            return np.asarray(im.convert("L"), dtype=np.uint8)

    def load_masks(self, i: int) -> np.ndarray:
        """Boolean (25, H, W); several polygons of one segment are OR-ed."""
        image_id = self.image_ids[i]
        info = self._images[image_id]
        height, width = info["height"], info["width"]
        masks = np.zeros((len(SEGMENT_NAMES), height, width), dtype=bool)
        for name, polygons in self._annotations[image_id]:
            for polygon in polygons:
                masks[_CHANNEL[name]] |= polygon_to_mask(polygon, height, width)
        return masks

    def class_counts(self) -> dict[str, int]:
        """Annotations per segment name (only names that occur)."""
        counts: dict[str, int] = {}
        for annotations in self._annotations.values():
            for name, _ in annotations:
                counts[name] = counts.get(name, 0) + 1
        return counts
