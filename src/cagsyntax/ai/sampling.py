"""Sampling weights that show rare segments to the model more often.

Most SYNTAX segments are absent from most ARCADE images, and the small branches appear in only a few. With
plain shuffling the model sees them rarely and learns to ignore them. Weighting each image by the rarest
segment it contains (an inverse-frequency weight softened by a power) fixes that without inventing data."""
from __future__ import annotations


def rare_segment_weights(counts: list[dict[str, int]], power: float = 0.5) -> list[float]:
    """One weight per image. `counts[i]` maps segment name -> number of annotations in image i.

    A segment's frequency is the number of images that contain it. An image's weight is
    (images / frequency) ** power of the rarest segment it holds, so it is 1.0 or more; an image with no
    segment gets 1.0. power 0 gives equal weights; larger values favour rare segments more."""
    if power < 0:
        raise ValueError("power must not be negative")
    total = len(counts)
    frequency: dict[str, int] = {}
    for image in counts:
        for name, number in image.items():
            if number > 0:
                frequency[name] = frequency.get(name, 0) + 1
    weights = []
    for image in counts:
        present = [name for name, number in image.items() if number > 0]
        weights.append(max(((total / frequency[name]) ** power for name in present), default=1.0))
    return weights
