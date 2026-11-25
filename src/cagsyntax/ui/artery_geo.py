"""Where the 25 SYNTAX segments run on the anterior heart illustration. Pure Python (no Qt).

Each segment is one cubic Bezier in image-relative coordinates (0..1, origin top-left of the picture) with a
width at its start and at its end (also image-relative) so it tapers. `visible` is True where the path follows an
artery that is drawn in the picture, False where the artery is hidden from the front (circumflex system,
posterior descending and posterolateral branches, left main) and the path is only a schematic position.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]


@dataclass(frozen=True)
class ArterySegment:
    points: tuple[Point, Point, Point, Point]
    width_start: float
    width_end: float
    visible: bool
    badge_t: float = 0.5          # where along the curve (0..1) the number badge sits; moved where badges would crowd


def _seg(p0: Point, p1: Point, p2: Point, p3: Point, w0: float, w1: float, visible: bool,
         badge_t: float = 0.5) -> ArterySegment:
    return ArterySegment((p0, p1, p2, p3), w0, w1, visible, badge_t)


ARTERY_GEO: dict[str, ArterySegment] = {
    # right coronary artery (visible from the front)
    "1": _seg((0.400, 0.455), (0.385, 0.500), (0.370, 0.540), (0.355, 0.585), 0.018, 0.016, True),
    "2": _seg((0.352, 0.585), (0.325, 0.620), (0.300, 0.660), (0.285, 0.715), 0.016, 0.015, True),
    "3": _seg((0.285, 0.715), (0.275, 0.750), (0.262, 0.795), (0.245, 0.825), 0.015, 0.013, True),
    # posterior descending and posterolateral branches (behind the heart)
    "4": _seg((0.245, 0.825), (0.300, 0.850), (0.370, 0.865), (0.440, 0.875), 0.012, 0.010, False),
    "16": _seg((0.440, 0.875), (0.470, 0.885), (0.510, 0.897), (0.540, 0.905), 0.010, 0.008, False),
    "16a": _seg((0.540, 0.905), (0.580, 0.885), (0.620, 0.870), (0.660, 0.860), 0.007, 0.006, False, 0.2),
    "16b": _seg((0.540, 0.905), (0.590, 0.905), (0.640, 0.910), (0.690, 0.915), 0.007, 0.006, False, 0.65),
    "16c": _seg((0.540, 0.905), (0.570, 0.930), (0.610, 0.945), (0.650, 0.955), 0.007, 0.006, False, 0.55),
    # left main (behind the pulmonary trunk)
    "5": _seg((0.470, 0.450), (0.490, 0.445), (0.510, 0.440), (0.530, 0.438), 0.018, 0.016, False),
    # left anterior descending (visible)
    "6": _seg((0.530, 0.438), (0.580, 0.440), (0.630, 0.460), (0.660, 0.485), 0.016, 0.015, True),
    "7": _seg((0.660, 0.485), (0.665, 0.540), (0.670, 0.620), (0.690, 0.690), 0.015, 0.013, True),
    "8": _seg((0.690, 0.690), (0.725, 0.750), (0.770, 0.840), (0.800, 0.930), 0.013, 0.008, True),
    # diagonals
    "9": _seg((0.655, 0.490), (0.700, 0.500), (0.730, 0.530), (0.760, 0.600), 0.011, 0.009, True),
    "9a": _seg((0.740, 0.560), (0.760, 0.600), (0.775, 0.640), (0.780, 0.680), 0.008, 0.006, False),
    "10": _seg((0.685, 0.620), (0.720, 0.640), (0.760, 0.680), (0.785, 0.740), 0.011, 0.008, True),
    "10a": _seg((0.785, 0.740), (0.787, 0.755), (0.787, 0.765), (0.785, 0.775), 0.007, 0.005, False, 0.35),
    # circumflex system (behind the heart)
    "11": _seg((0.530, 0.438), (0.575, 0.415), (0.640, 0.408), (0.700, 0.430), 0.014, 0.012, False, 0.7),
    "12": _seg((0.580, 0.450), (0.600, 0.500), (0.615, 0.560), (0.620, 0.620), 0.008, 0.007, False),
    "12a": _seg((0.620, 0.620), (0.635, 0.660), (0.650, 0.700), (0.655, 0.750), 0.007, 0.006, False, 0.7),
    "12b": _seg((0.620, 0.620), (0.605, 0.660), (0.595, 0.700), (0.590, 0.730), 0.007, 0.006, False),
    "13": _seg((0.700, 0.440), (0.760, 0.500), (0.800, 0.580), (0.820, 0.660), 0.012, 0.010, False),
    "14": _seg((0.820, 0.660), (0.835, 0.700), (0.835, 0.740), (0.830, 0.780), 0.010, 0.008, False),
    "14a": _seg((0.830, 0.780), (0.835, 0.810), (0.830, 0.840), (0.820, 0.870), 0.007, 0.006, False, 0.8),
    "14b": _seg((0.830, 0.780), (0.815, 0.800), (0.800, 0.815), (0.790, 0.830), 0.007, 0.006, False, 0.5),
    "15": _seg((0.565, 0.600), (0.550, 0.650), (0.545, 0.700), (0.540, 0.740), 0.008, 0.007, False),
}


def bezier(points, t: float) -> Point:
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = points
    u = 1.0 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3)


def sample(points, n: int = 24) -> list[Point]:
    """n + 1 points along the curve, from its start to its end."""
    return [bezier(points, i / n) for i in range(n + 1)]


def midpoint(seg_id: str) -> Point:
    return bezier(ARTERY_GEO[seg_id].points, 0.5)


def badge_point(seg_id: str) -> Point:
    """Where the number badge of a segment is drawn: on its own curve, at `badge_t`."""
    g = ARTERY_GEO[seg_id]
    return bezier(g.points, g.badge_t)


def outline(points: list[Point], width_start: float, width_end: float) -> list[Point]:
    """Polygon around a polyline: one side forwards, the other back, tapering from width_start to width_end."""
    n = len(points)
    left: list[Point] = []
    right: list[Point] = []
    for i, (x, y) in enumerate(points):
        ax, ay = points[max(i - 1, 0)]
        bx, by = points[min(i + 1, n - 1)]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        half = (width_start + (width_end - width_start) * i / (n - 1)) / 2
        left.append((x + nx * half, y + ny * half))
        right.append((x - nx * half, y - ny * half))
    return left + right[::-1]
