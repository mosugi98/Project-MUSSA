# Coronary artery map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a realistic heart-illustration segment picker ("Diagram") beside the existing stick-figure tree ("Schematic") in the scoring panel, with all 25 SYNTAX segments clickable on it.

**Architecture:** `ArteryMap` subclasses `SegmentTree`, so selection state, dominance filtering, click handling and the signal are reused unchanged. It overrides only the canvas scale, hit-testing and painting. Segment geometry (cubic Beziers in image-relative coordinates) lives in a pure-Python table `artery_geo.py`. `ScoringPanel` holds both pickers in a stacked widget with a two-button switch and falls back to the Schematic when the image is missing.

**Tech Stack:** Python 3.12, PySide6 (QPainter, QPixmap), Pillow (one-off image prep), pytest, PyInstaller (packaging).

Spec: `docs/superpowers/specs/2026-11-24-artery-map-design.md`.

## Global Constraints

- Artwork licence: CC BY 4.0, "202410 Coronary arteries anterior view" by DataBase Center for Life Science (DBCLS), credit/source https://doi.org/10.7875/togopic.2024.242. Credit text shown in the app: `Heart illustration: DBCLS, CC BY 4.0, modified`.
- The CC BY-SA image (`Coronary_arteries.svg`) must NOT be bundled.
- No change to the scoring engine, form questions, stored data or export format.
- `SegmentTree` keeps its behaviour and tests; the existing suite (885 passed, 3 oracle tests passing, 3 skipped for missing `torch`/ARCADE as of 2026-11-24) must stay green.
- Hidden-from-the-front segments are drawn dashed with the legend `Dashed: position is schematic (not visible from the front)`.
- If the image cannot be loaded, scoring is never blocked: the panel falls back to the Schematic.
- Commands run from `C:\Users\DESKTOP\Project-MUSSA` with the Python 3.12 environment that has the project installed (`pip install -e ".[test]"`). Below, `python` means that interpreter. Tests run headless (`QT_QPA_PLATFORM=offscreen` is set by the tests).
- Commit messages end with: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`

## File Structure

| File | Responsibility |
|---|---|
| `src/cagsyntax/ui/assets/heart_anterior.png` (new) | The 1200 x 1200 backdrop |
| `src/cagsyntax/ui/assets/LICENSE-artwork.md` (new) | Title, author, licence, source, modifications |
| `src/cagsyntax/ui/artery_geo.py` (new) | `ARTERY_GEO` table plus pure geometry helpers (no Qt) |
| `src/cagsyntax/ui/artery_map.py` (new) | `ArteryMap` widget |
| `src/cagsyntax/ui/scoring_panel.py` (modify) | Stacked pickers, switch, fallback |
| `tools/ui/render_artery_map.py` (new) | Offscreen PNG renders for the calibration and owner review |
| `src/cagsyntax/selftest.py`, `tools/packaging/build_exe.py`, `pyproject.toml` (modify) | Ship and verify the asset |
| `tests/test_artery_assets.py`, `tests/test_artery_geo.py`, `tests/test_artery_map.py`, `tests/test_scoring_panel_picker.py`, `tests/test_packaging_assets.py` (new), `tests/test_selftest.py` (modify) | Tests |
| `CHANGELOG.md` (modify) | Entry under Unreleased |

---

### Task 1: Artwork asset and licence file

**Files:**
- Create: `src/cagsyntax/ui/assets/heart_anterior.png`, `src/cagsyntax/ui/assets/LICENSE-artwork.md`
- Modify: `pyproject.toml`
- Test: `tests/test_artery_assets.py`

**Interfaces:**
- Produces: the file `src/cagsyntax/ui/assets/heart_anterior.png` (1200 x 1200, RGBA) that `artery_map.IMAGE_PATH` points to in Task 3.

- [ ] **Step 1: Write the failing test**

Create `tests/test_artery_assets.py`:

```python
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / "src" / "cagsyntax" / "ui" / "assets"


def test_heart_image_is_a_1200_square_with_transparency():
    with Image.open(ASSETS / "heart_anterior.png") as im:
        assert im.size == (1200, 1200)
        assert im.mode == "RGBA"


def test_licence_file_names_author_licence_and_source():
    text = (ASSETS / "LICENSE-artwork.md").read_text(encoding="utf-8")
    for needle in ("DBCLS", "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0",
                   "https://doi.org/10.7875/togopic.2024.242", "modified"):
        assert needle in text


def test_the_share_alike_image_is_not_bundled():
    names = {p.name.lower() for p in ASSETS.iterdir()}
    assert not any("coronary_arteries.svg" in n for n in names)
```

- [ ] **Step 2: Run it to see it fail**

Run: `python -m pytest tests/test_artery_assets.py -q`
Expected: FAIL (`FileNotFoundError` for `heart_anterior.png`).

- [ ] **Step 3: Create the asset and licence file**

Run (converts the owner's downloaded 3840 px `.webp` to a 1200 px PNG; if the source file is elsewhere, change the path):

```bash
mkdir -p src/cagsyntax/ui/assets
python -c "
from PIL import Image
src = r'C:\Users\DESKTOP\Downloads\3840px-202410_Coronary_arteries_anterior_view.svg.webp'
im = Image.open(src).convert('RGBA').resize((1200, 1200), Image.LANCZOS)
im.save('src/cagsyntax/ui/assets/heart_anterior.png', optimize=True)
print(im.size)"
```

Create `src/cagsyntax/ui/assets/LICENSE-artwork.md`:

```markdown
# Artwork licence

**Title:** 202410 Coronary arteries anterior view
**Author:** DataBase Center for Life Science (DBCLS)
**Licence:** CC BY 4.0, https://creativecommons.org/licenses/by/4.0
**Source:** https://doi.org/10.7875/togopic.2024.242 (Wikimedia Commons: File:202410 Coronary arteries anterior view.svg)

**Modifications:** the artwork was modified for use in MUSSA. The original vector drawing was used as a 3840 x 3840
raster preview, resized to 1200 x 1200 pixels and saved as PNG (`heart_anterior.png`). MUSSA draws the 25 SYNTAX
segments over it. The original author does not endorse MUSSA.
```

Add to the end of `pyproject.toml`'s setuptools section (after `[tool.setuptools.packages.find]` block):

```toml
[tool.setuptools.package-data]
"cagsyntax.ui" = ["assets/*"]
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_artery_assets.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cagsyntax/ui/assets tests/test_artery_assets.py pyproject.toml
git commit -m "Add the CC BY heart illustration and its licence file

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Segment geometry table and helpers

**Files:**
- Create: `src/cagsyntax/ui/artery_geo.py`
- Test: `tests/test_artery_geo.py`

**Interfaces:**
- Produces (used by Task 3):
  - `ArterySegment(points, width_start, width_end, visible)` frozen dataclass; `points` is 4 `(x, y)` tuples in 0..1 image coordinates.
  - `ARTERY_GEO: dict[str, ArterySegment]` with exactly the 25 ids of `SEGMENT_IDS`.
  - `bezier(points, t) -> (x, y)`, `sample(points, n=24) -> list[(x, y)]` (n + 1 points), `midpoint(seg_id) -> (x, y)` (Bezier at t = 0.5), `outline(points, width_start, width_end) -> list[(x, y)]` (ribbon polygon, tapered).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_artery_geo.py`:

```python
import math

from cagsyntax.scoring.tables import SEGMENT_IDS
from cagsyntax.ui.artery_geo import ARTERY_GEO, bezier, midpoint, outline, sample


def test_table_covers_exactly_the_25_segments():
    assert set(ARTERY_GEO) == set(SEGMENT_IDS)
    assert len(ARTERY_GEO) == 25


def test_every_control_point_is_inside_the_picture_and_widths_are_positive():
    for seg, g in ARTERY_GEO.items():
        assert len(g.points) == 4, seg
        for x, y in g.points:
            assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0, (seg, x, y)
        assert g.width_start > 0 and g.width_end > 0, seg


def test_arteries_drawn_in_the_picture_are_marked_visible_and_hidden_ones_are_not():
    for seg in ("1", "2", "3", "6", "7", "8"):
        assert ARTERY_GEO[seg].visible, seg
    for seg in ("5", "11", "13", "14", "15", "16"):
        assert not ARTERY_GEO[seg].visible, seg


def test_bezier_endpoints_and_midpoint_of_a_straight_line():
    pts = ((0.0, 0.5), (1 / 3, 0.5), (2 / 3, 0.5), (1.0, 0.5))
    assert bezier(pts, 0.0) == (0.0, 0.5)
    assert bezier(pts, 1.0) == (1.0, 0.5)
    x, y = bezier(pts, 0.5)
    assert math.isclose(x, 0.5) and math.isclose(y, 0.5)


def test_sample_returns_n_plus_one_points_ending_on_the_curve_ends():
    pts = ARTERY_GEO["6"].points
    s = sample(pts, 24)
    assert len(s) == 25
    assert s[0] == bezier(pts, 0.0) and s[-1] == bezier(pts, 1.0)


def test_midpoint_matches_the_bezier_at_one_half():
    assert midpoint("8") == bezier(ARTERY_GEO["8"].points, 0.5)


def test_outline_is_a_ribbon_that_tapers():
    line = ((0.0, 0.5), (1 / 3, 0.5), (2 / 3, 0.5), (1.0, 0.5))
    poly = outline(sample(line, 10), 0.10, 0.02)
    assert len(poly) == 22                                    # 11 points down one side, 11 back up the other
    ys_start = [y for x, y in poly if x < 0.01]
    ys_end = [y for x, y in poly if x > 0.99]
    assert math.isclose(max(ys_start) - min(ys_start), 0.10, abs_tol=1e-9)
    assert math.isclose(max(ys_end) - min(ys_end), 0.02, abs_tol=1e-9)
```

- [ ] **Step 2: Run to see them fail**

Run: `python -m pytest tests/test_artery_geo.py -q`
Expected: FAIL (`ModuleNotFoundError: cagsyntax.ui.artery_geo`).

- [ ] **Step 3: Implement**

Create `src/cagsyntax/ui/artery_geo.py`. The coordinates are a first estimate traced by eye from the 1000 px preview of the artwork (x to the right, y down, both 0..1). Task 5 refines them against rendered images and the owner's review.

```python
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


def _seg(p0: Point, p1: Point, p2: Point, p3: Point, w0: float, w1: float, visible: bool) -> ArterySegment:
    return ArterySegment((p0, p1, p2, p3), w0, w1, visible)


ARTERY_GEO: dict[str, ArterySegment] = {
    # right coronary artery (visible from the front)
    "1": _seg((0.400, 0.455), (0.385, 0.500), (0.370, 0.540), (0.355, 0.585), 0.018, 0.016, True),
    "2": _seg((0.355, 0.585), (0.335, 0.620), (0.310, 0.660), (0.295, 0.715), 0.016, 0.015, True),
    "3": _seg((0.295, 0.715), (0.285, 0.750), (0.265, 0.800), (0.245, 0.825), 0.015, 0.013, True),
    # posterior descending and posterolateral branches (behind the heart)
    "4": _seg((0.245, 0.825), (0.300, 0.850), (0.370, 0.865), (0.440, 0.875), 0.012, 0.010, False),
    "16": _seg((0.440, 0.875), (0.500, 0.890), (0.550, 0.910), (0.600, 0.920), 0.010, 0.008, False),
    "16a": _seg((0.600, 0.920), (0.640, 0.930), (0.670, 0.945), (0.700, 0.950), 0.007, 0.006, False),
    "16b": _seg((0.600, 0.920), (0.630, 0.905), (0.660, 0.900), (0.690, 0.905), 0.007, 0.006, False),
    "16c": _seg((0.600, 0.920), (0.620, 0.950), (0.650, 0.960), (0.680, 0.965), 0.007, 0.006, False),
    # left main (behind the pulmonary trunk)
    "5": _seg((0.470, 0.450), (0.490, 0.445), (0.510, 0.440), (0.530, 0.438), 0.018, 0.016, False),
    # left anterior descending (visible)
    "6": _seg((0.530, 0.438), (0.580, 0.440), (0.630, 0.460), (0.660, 0.485), 0.016, 0.015, True),
    "7": _seg((0.660, 0.485), (0.665, 0.540), (0.670, 0.620), (0.690, 0.690), 0.015, 0.013, True),
    "8": _seg((0.690, 0.690), (0.720, 0.750), (0.760, 0.840), (0.800, 0.930), 0.013, 0.008, True),
    # diagonals
    "9": _seg((0.655, 0.490), (0.700, 0.500), (0.730, 0.530), (0.760, 0.600), 0.011, 0.009, True),
    "9a": _seg((0.740, 0.560), (0.760, 0.600), (0.775, 0.640), (0.780, 0.680), 0.008, 0.006, False),
    "10": _seg((0.685, 0.620), (0.720, 0.640), (0.760, 0.680), (0.785, 0.740), 0.011, 0.008, True),
    "10a": _seg((0.785, 0.740), (0.790, 0.770), (0.795, 0.800), (0.800, 0.830), 0.007, 0.005, False),
    # circumflex system (behind the heart)
    "11": _seg((0.530, 0.438), (0.580, 0.425), (0.640, 0.420), (0.700, 0.440), 0.014, 0.012, False),
    "12": _seg((0.580, 0.450), (0.600, 0.500), (0.615, 0.560), (0.620, 0.620), 0.008, 0.007, False),
    "12a": _seg((0.620, 0.620), (0.635, 0.660), (0.650, 0.700), (0.655, 0.750), 0.007, 0.006, False),
    "12b": _seg((0.620, 0.620), (0.605, 0.660), (0.595, 0.700), (0.590, 0.730), 0.007, 0.006, False),
    "13": _seg((0.700, 0.440), (0.760, 0.500), (0.800, 0.580), (0.820, 0.660), 0.012, 0.010, False),
    "14": _seg((0.820, 0.660), (0.835, 0.700), (0.835, 0.740), (0.830, 0.780), 0.010, 0.008, False),
    "14a": _seg((0.830, 0.780), (0.835, 0.810), (0.830, 0.840), (0.820, 0.870), 0.007, 0.006, False),
    "14b": _seg((0.830, 0.780), (0.820, 0.790), (0.810, 0.795), (0.805, 0.800), 0.007, 0.006, False),
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
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_artery_geo.py -q`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cagsyntax/ui/artery_geo.py tests/test_artery_geo.py
git commit -m "Add the segment geometry table for the artery map

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The ArteryMap widget

**Files:**
- Create: `src/cagsyntax/ui/artery_map.py`
- Test: `tests/test_artery_map.py`

**Interfaces:**
- Consumes: Task 1 `heart_anterior.png`; Task 2 `ARTERY_GEO`, `sample`, `midpoint`, `outline`; existing `SegmentTree` (`_applicable`, `_normalise`, `_selected`, `_first`, `mousePressEvent`, signal `selection_changed`) and `_distance_to_segment` from `segment_tree.py`; `theme as T`.
- Produces (used by Task 4/5/6): `ArteryMap(parent=None, image_path: Path | None = None)` with the full `SegmentTree` interface plus `image_available() -> bool`; module constants `IMAGE_PATH: Path`, `CANVAS = 1000.0`, `CAPTION_H = 34`, `LEGEND`, `CREDIT`; `load_heart(path=None) -> QPixmap | None`. Logical coordinates are 0..1000 over the picture. At widget size `(1000, 1000 + CAPTION_H)` the scale is 1 with no offset.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_artery_map.py`:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from cagsyntax.scoring.tables import SEGMENT_IDS, weight
from cagsyntax.ui import theme as T
from cagsyntax.ui.artery_geo import midpoint
from cagsyntax.ui.artery_map import CANVAS, CAPTION_H, ArteryMap
from cagsyntax.ui.segment_tree import SegmentTree


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def mid(seg):
    x, y = midpoint(seg)
    return x * CANVAS, y * CANVAS


@pytest.fixture
def amap(qapp):
    m = ArteryMap()
    m.resize(int(CANVAS), int(CANVAS) + CAPTION_H)       # scale 1, no offset
    m.set_scoring_dominance("right")
    return m


def click(widget, x, y):
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(round(x), round(y)))


def test_it_is_a_segment_picker(amap):
    assert isinstance(amap, SegmentTree)
    assert amap.image_available()


def test_every_applicable_segment_is_hit_at_its_midpoint(amap):
    for dom in ("right", "left"):
        amap.set_scoring_dominance(dom)
        for seg in SEGMENT_IDS:
            expected = seg if weight(seg, dom) is not None else None
            assert amap.segment_at(*mid(seg)) == expected, (dom, seg)


def test_empty_space_and_no_dominance_hit_nothing(amap):
    assert amap.segment_at(5, 5) is None
    amap.set_scoring_dominance(None)
    assert amap.segment_at(*mid("6")) is None


def test_clicking_toggles_and_emits_in_table_order(amap):
    spy = QSignalSpy(amap.selection_changed)
    for seg in ("8", "6"):
        click(amap, *mid(seg))
    assert amap.selected() == ["6", "8"]
    assert spy.count() == 2 and spy.at(1)[0] == ["6", "8"]
    click(amap, *mid("6"))
    assert amap.selected() == ["8"]


def test_clicking_a_segment_that_does_not_exist_for_the_dominance_does_nothing(amap):
    amap.set_scoring_dominance("left")
    spy = QSignalSpy(amap.selection_changed)
    click(amap, *mid("4"))
    assert amap.selected() == [] and spy.count() == 0


def test_hit_testing_scales_with_a_bigger_widget(qapp):
    m = ArteryMap()
    m.set_scoring_dominance("right")
    m.resize(2000, 2000 + CAPTION_H)                       # scale 2
    x, y = mid("6")
    click(m, 2 * x, 2 * y)
    assert m.selected() == ["6"]


def test_hit_testing_centres_the_picture_in_a_wide_widget(qapp):
    m = ArteryMap()
    m.set_scoring_dominance("right")
    m.resize(1400, 700 + CAPTION_H)                        # scale 0.7, picture centred horizontally
    x, y = mid("7")
    click(m, 350 + 0.7 * x, 0.7 * y)
    assert m.selected() == ["7"]


def test_first_segment_marker_and_painting_do_not_crash(amap):
    amap.set_selected(["2", "3"])
    amap.set_first_segment("2")
    assert amap.first_segment() == "2"
    amap.grab()


def test_selected_segments_follow_the_theme(amap):
    amap.set_selected(["6"])
    x, y = mid("6")
    before = amap.grab().toImage().pixelColor(round(x) - 8, round(y)).name()
    assert before.lower() == T.get_theme().primary.lower()
    T.set_theme(T.get_theme().with_changes(primary="#0A5A2A"))
    assert amap.grab().toImage().pixelColor(round(x) - 8, round(y)).name().lower() == "#0a5a2a"


def test_a_missing_image_is_reported_and_painting_still_works(qapp, tmp_path):
    m = ArteryMap(image_path=tmp_path / "nope.png")
    m.resize(500, 500 + CAPTION_H)
    assert not m.image_available()
    m.grab()
```

- [ ] **Step 2: Run to see them fail**

Run: `python -m pytest tests/test_artery_map.py -q`
Expected: FAIL (`ModuleNotFoundError: cagsyntax.ui.artery_map`).

- [ ] **Step 3: Implement**

Create `src/cagsyntax/ui/artery_map.py`:

```python
"""Realistic segment picker: the DBCLS anterior heart illustration with the 25 SYNTAX segments drawn on it.

Same interface as `SegmentTree` (it is one): the base class keeps the selection, the dominance rules and the click
handling. This class changes only the canvas scale, the hit test and the painting. Logical coordinates run 0..1000
over the picture; a caption strip of CAPTION_H pixels under it carries the legend and the artwork credit."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPolygonF

from ..scoring.tables import SEGMENT_IDS
from . import theme as T
from .artery_geo import ARTERY_GEO, midpoint, outline, sample
from .segment_tree import SegmentTree, _distance_to_segment

CANVAS = 1000.0
CAPTION_H = 34
HIT_LOGICAL = 20.0           # click tolerance in logical units
BADGE_PX = 14.0              # the number badge is always clickable
IMAGE_PATH = Path(__file__).parent / "assets" / "heart_anterior.png"
LEGEND = "Dashed: position is schematic (not visible from the front)"
CREDIT = "Heart illustration: DBCLS, CC BY 4.0, modified"

_POLYLINES = {seg: [(x * CANVAS, y * CANVAS) for x, y in sample(g.points)] for seg, g in ARTERY_GEO.items()}
_pixmaps: dict[str, QPixmap | None] = {}


def load_heart(path: Path | None = None) -> QPixmap | None:
    """The backdrop, loaded once per file. None when the file is missing or unreadable."""
    target = Path(path) if path is not None else IMAGE_PATH
    key = str(target)
    if key not in _pixmaps:
        pixmap = QPixmap(key)
        _pixmaps[key] = None if pixmap.isNull() else pixmap
    return _pixmaps[key]


class ArteryMap(SegmentTree):
    def __init__(self, parent=None, image_path: Path | None = None):
        super().__init__(parent)
        self._pixmap = load_heart(image_path)
        self.setMinimumSize(360, 360 + CAPTION_H)

    def image_available(self) -> bool:
        return self._pixmap is not None

    # ---- geometry ----
    def _scale(self) -> tuple[float, float, float]:
        available_h = max(1, self.height() - CAPTION_H)
        s = min(self.width(), available_h) / CANVAS
        return s, (self.width() - CANVAS * s) / 2, (available_h - CANVAS * s) / 2

    def segment_at(self, x: float, y: float) -> str | None:
        """Segment nearest to a point given in logical (0..1000) coordinates, within the click tolerance."""
        s, _ox, _oy = self._scale()
        radius = max(HIT_LOGICAL, BADGE_PX / s) if s > 0 else HIT_LOGICAL
        best, best_d = None, radius
        for seg in SEGMENT_IDS:
            if not self._applicable(seg):
                continue
            pts = _POLYLINES[seg]
            d = min(_distance_to_segment(x, y, ax, ay, bx, by) for (ax, ay), (bx, by) in zip(pts, pts[1:]))
            if d < best_d:                                   # strict: a tie keeps the earlier segment
                best, best_d = seg, d
        return best

    # ---- painting ----
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pal = self.palette()
        th = T.get_theme()
        if self._pixmap is None:
            p.setPen(pal.placeholderText().color())
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Diagram image missing")
            p.end()
            return
        s, ox, oy = self._scale()
        accent, ink = QColor(th.primary), QColor(th.text)

        p.save()
        p.translate(ox, oy)
        p.scale(s, s)
        p.drawPixmap(QRectF(0, 0, CANVAS, CANVAS), self._pixmap, QRectF(self._pixmap.rect()))
        for seg in SEGMENT_IDS:
            if not self._applicable(seg):
                continue
            g, on = ARTERY_GEO[seg], seg in self._selected
            ribbon = QPolygonF([QPointF(x, y) for x, y in
                                outline(_POLYLINES[seg], g.width_start * CANVAS, g.width_end * CANVAS)])
            fill = QColor(accent) if on else QColor(ink)
            fill.setAlpha(235 if on else (70 if g.visible else 35))
            edge = QPen(QColor(th.primary_dark) if on else ink, 1.5 if (on or not g.visible) else 1.0)
            edge.setCosmetic(True)
            if not g.visible:
                edge.setStyle(Qt.PenStyle.DashLine)
            p.setPen(edge)
            p.setBrush(fill)
            p.drawPolygon(ribbon)
        p.restore()

        font = QFont(self.font())
        font.setPixelSize(10)
        font.setBold(True)
        p.setFont(font)
        for seg in SEGMENT_IDS:
            if not self._applicable(seg):
                continue
            on = seg in self._selected
            mx, my = midpoint(seg)
            cx, cy = ox + mx * CANVAS * s, oy + my * CANVAS * s
            r = 13 if len(seg) > 2 else 11
            ring = QPen(QColor(th.accent) if seg == self._first else (accent if on else ink),
                        3 if seg == self._first else 2)
            p.setPen(ring)
            p.setBrush(accent if on else QColor(th.surface))
            p.drawEllipse(QPointF(cx, cy), r, r)
            p.setPen(QColor(th.on_primary) if on else QColor(th.text))
            p.drawText(QRectF(cx - r, cy - r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, seg)

        caption = QFont(self.font())
        caption.setPixelSize(9)
        p.setFont(caption)
        p.setPen(pal.placeholderText().color())
        p.drawText(QRectF(0, self.height() - CAPTION_H, self.width(), CAPTION_H),
                   Qt.AlignmentFlag.AlignCenter, f"{LEGEND}\n{CREDIT}")
        p.end()
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_artery_map.py tests/test_segment_tree.py -q`
Expected: all pass (the tree's own tests still pass because `SegmentTree` is unchanged).

If `test_every_applicable_segment_is_hit_at_its_midpoint` fails for a segment, two paths cross exactly at that midpoint. Move one segment's control points slightly in `artery_geo.py` and rerun.

- [ ] **Step 5: Commit**

```bash
git add src/cagsyntax/ui/artery_map.py tests/test_artery_map.py
git commit -m "Add the ArteryMap widget: heart illustration with clickable segments

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Panel switch (Diagram | Schematic) with fallback

**Files:**
- Modify: `src/cagsyntax/ui/scoring_panel.py` (imports at lines 3-12; picker creation at 195-199; `_sync` at 281-284)
- Test: `tests/test_scoring_panel_picker.py`

**Interfaces:**
- Consumes: Task 3 `ArteryMap`, `ArteryMap.image_available()`, `artery_map.IMAGE_PATH`, `artery_map.CANVAS`, `artery_map.CAPTION_H`.
- Produces: on `ScoringPanel`: attributes `tree` (SegmentTree, unchanged name), `map` (ArteryMap), `picker_stack` (QStackedWidget), `diagram_button`, `schematic_button` (checkable QPushButtons); methods `show_picker(name: str)` (`"diagram"` or `"schematic"`; `"diagram"` is ignored when the image is missing) and `current_picker() -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scoring_panel_picker.py`:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cagsyntax.ui import artery_map
from cagsyntax.ui.artery_geo import midpoint
from cagsyntax.ui.artery_map import CANVAS, CAPTION_H
from cagsyntax.ui.scoring_panel import ScoringPanel


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_the_diagram_is_the_default_and_the_switch_changes_the_picker(qapp):
    panel = ScoringPanel()
    assert panel.current_picker() == "diagram"
    assert panel.picker_stack.currentWidget() is panel.map
    panel.show_picker("schematic")
    assert panel.current_picker() == "schematic"
    assert panel.picker_stack.currentWidget() is panel.tree
    assert panel.schematic_button.isChecked() and not panel.diagram_button.isChecked()
    panel.show_picker("diagram")
    assert panel.diagram_button.isChecked()


def test_a_selection_is_shown_on_both_pickers(qapp):
    panel = ScoringPanel()
    panel.set_dominance("right")
    panel.toggle_segment("6")
    assert panel.tree.selected() == ["6"] and panel.map.selected() == ["6"]


def test_clicking_on_the_diagram_edits_the_lesion(qapp):
    panel = ScoringPanel()
    panel.set_dominance("right")
    panel.map.resize(int(CANVAS), int(CANVAS) + CAPTION_H)
    x, y = midpoint("7")
    QTest.mouseClick(panel.map, Qt.MouseButton.LeftButton, pos=QPoint(round(x * CANVAS), round(y * CANVAS)))
    assert panel.case().lesions[0].segments == ["7"]
    assert panel.tree.selected() == ["7"]


def test_a_missing_image_falls_back_to_the_schematic(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(artery_map, "IMAGE_PATH", tmp_path / "missing.png")
    panel = ScoringPanel()
    assert panel.current_picker() == "schematic"
    assert not panel.diagram_button.isEnabled()
    panel.show_picker("diagram")                       # ignored: there is no image
    assert panel.current_picker() == "schematic"
```

- [ ] **Step 2: Run to see them fail**

Run: `python -m pytest tests/test_scoring_panel_picker.py -q`
Expected: FAIL (`AttributeError: ... has no attribute 'current_picker'`).

- [ ] **Step 3: Implement**

In `src/cagsyntax/ui/scoring_panel.py`, change the import block (lines 3-6) to:

```python
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QListWidget, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)
```

and add below the existing `from .segment_tree import SegmentTree` line:

```python
from .artery_map import ArteryMap
```

Replace these lines in `_build` (currently lines 195-199):

```python
        self.tree = SegmentTree()
        self.tree.selection_changed.connect(self._on_tree)
        left.addWidget(self.lesion_list)
        left.addLayout(buttons)
        left.addWidget(self.tree, 1)
```

with:

```python
        self.tree = SegmentTree()
        self.map = ArteryMap()
        for picker in (self.map, self.tree):
            picker.selection_changed.connect(self._on_tree)
        self.picker_stack = QStackedWidget()
        self.picker_stack.addWidget(self.map)          # index 0: Diagram
        self.picker_stack.addWidget(self.tree)         # index 1: Schematic
        self.diagram_button = QPushButton("Diagram")
        self.schematic_button = QPushButton("Schematic")
        switch = QHBoxLayout()
        self._picker_group = QButtonGroup(self)
        self._picker_group.setExclusive(True)
        for button, name in ((self.diagram_button, "diagram"), (self.schematic_button, "schematic")):
            button.setCheckable(True)
            self._picker_group.addButton(button)
            button.clicked.connect(lambda _checked=False, n=name: self.show_picker(n))
            switch.addWidget(button)
        switch.addStretch(1)
        self.diagram_button.setEnabled(self.map.image_available())
        self.show_picker("diagram" if self.map.image_available() else "schematic")
        left.addWidget(self.lesion_list)
        left.addLayout(buttons)
        left.addLayout(switch)
        left.addWidget(self.picker_stack, 1)
```

Add these two methods to `ScoringPanel` (next to `_on_tree`):

```python
    def show_picker(self, name: str) -> None:
        """Show the realistic Diagram or the stick-figure Schematic. The Diagram needs its image."""
        if name == "diagram" and self.map.image_available():
            self.picker_stack.setCurrentWidget(self.map)
            self.diagram_button.setChecked(True)
        else:
            self.picker_stack.setCurrentWidget(self.tree)
            self.schematic_button.setChecked(True)

    def current_picker(self) -> str:
        return "diagram" if self.picker_stack.currentWidget() is self.map else "schematic"
```

Replace the four tree calls in `_sync` (currently lines 281-284):

```python
            self.tree.set_scoring_dominance(dom)
            self.tree.set_selected(les.segments if les else [])
            self.tree.set_first_segment(les.first_segment if les else None)
            self.tree.setEnabled(les is not None)
```

with:

```python
            for picker in (self.tree, self.map):
                picker.set_scoring_dominance(dom)
                picker.set_selected(les.segments if les else [])
                picker.set_first_segment(les.first_segment if les else None)
                picker.setEnabled(les is not None)
```

- [ ] **Step 4: Run the panel tests and the existing UI tests**

Run: `python -m pytest tests/test_scoring_panel_picker.py tests/test_scoring_panel.py tests/ui tests/test_segment_tree.py tests/test_artery_map.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/cagsyntax/ui/scoring_panel.py tests/test_scoring_panel_picker.py
git commit -m "Scoring panel: Diagram | Schematic picker switch with image fallback

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Render check, calibration and owner review

The first geometry is an estimate. This task renders the map, corrects obvious misplacements, and gets the owner's clinical review. It changes only `artery_geo.py` (and the render script).

**Files:**
- Create: `tools/ui/render_artery_map.py`
- Modify: `src/cagsyntax/ui/artery_geo.py` (control points and widths only)

**Interfaces:**
- Consumes: `ArteryMap`, `CANVAS`, `CAPTION_H`, theme `PRESETS`/`COLOR_TOKENS`, `set_theme`.
- Produces: PNG files in a folder given by `--out` named `map_<dominance>_<theme>_<mode>.png` (dominance `right`/`left`, theme `meadow`/`forest`, mode `idle`/`all`).

- [ ] **Step 1: Write the render script**

Create `tools/ui/render_artery_map.py`:

```python
"""Render the artery map offscreen to PNG files for checking segment placement.

    python tools/ui/render_artery_map.py --out <folder>

Writes map_<dominance>_<theme>_<mode>.png: dominance right/left, theme meadow (light) / forest (dark), mode
idle (nothing selected) / all (every applicable segment selected, first segment ringed)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from PySide6.QtWidgets import QApplication  # noqa: E402

from cagsyntax.scoring.tables import SEGMENT_IDS, weight  # noqa: E402
from cagsyntax.ui import theme as T  # noqa: E402
from cagsyntax.ui.artery_map import CANVAS, CAPTION_H, ArteryMap  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the artery map to PNG files.")
    parser.add_argument("--out", required=True, help="folder for the PNG files")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    for theme_name in ("meadow", "forest"):
        T.set_theme(T.get_theme().with_changes(**{k: T.PRESETS[theme_name][k] for k in T.COLOR_TOKENS}))
        for dom in ("right", "left"):
            for mode in ("idle", "all"):
                widget = ArteryMap()
                widget.resize(int(CANVAS), int(CANVAS) + CAPTION_H)
                widget.set_scoring_dominance(dom)
                if mode == "all":
                    chosen = [s for s in SEGMENT_IDS if weight(s, dom) is not None]
                    widget.set_selected(chosen)
                    widget.set_first_segment("6")
                target = out / f"map_{dom}_{theme_name}_{mode}.png"
                widget.grab().save(str(target))
                print("wrote", target)
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Render**

Run: `python tools/ui/render_artery_map.py --out C:\Users\DESKTOP\MUSSA-review`
Expected: eight lines `wrote ...map_..._....png`.

- [ ] **Step 3: Inspect the renders and correct obvious problems**

Open `map_right_meadow_idle.png` and `map_right_meadow_all.png` (Read tool, or any image viewer). Check, and fix in `ARTERY_GEO`:
1. Visible segments (`1 2 3 6 7 8 9 10`) lie on the artery drawn in the picture, not beside it.
2. No two number badges overlap. If they do, move one segment's control points a little, or shorten its path.
3. Hidden segments (dashed) lie inside the heart outline and do not cross the aorta or the great vessels.
4. After each edit, rerun: `python -m pytest tests/test_artery_geo.py tests/test_artery_map.py -q` (the midpoint test catches paths that cross at a midpoint), then re-render.
Repeat until steps 1-3 hold in `meadow` and `forest` for `right` and `left`.

- [ ] **Step 4: Owner review**

Ask the project owner to open the PNGs in `C:\Users\DESKTOP\MUSSA-review` and confirm segment placement (the picture is a front view: hidden segments are labelled schematic). Apply their corrections in `artery_geo.py`, rerun the tests and the render, and ask again until they approve. Do not continue to Task 6 before approval.

- [ ] **Step 5: Run the geometry and widget tests, then commit**

Run: `python -m pytest tests/test_artery_geo.py tests/test_artery_map.py tests/test_scoring_panel_picker.py -q`
Expected: all pass.

```bash
git add tools/ui/render_artery_map.py src/cagsyntax/ui/artery_geo.py
git commit -m "Calibrate segment paths on the heart illustration and add the render tool

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Ship the asset, verify it in the self-test, document

**Files:**
- Modify: `tools/packaging/build_exe.py` (imports and `pyinstaller_command`, lines 9-60), `src/cagsyntax/selftest.py` (`CHECKS`, lines 69-90), `CHANGELOG.md`
- Test: `tests/test_packaging_assets.py` (new), `tests/test_selftest.py` (modify)

**Interfaces:**
- Consumes: `artery_map.IMAGE_PATH`.
- Produces: a PyInstaller `--add-data` entry for the assets folder; a self-test check named `Diagram image (artery map)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_packaging_assets.py`:

```python
from tools.packaging import build_exe


def test_the_build_command_ships_the_artwork_folder():
    cmd = build_exe.pyinstaller_command()
    assert "--add-data" in cmd
    spec = cmd[cmd.index("--add-data") + 1]
    source, _sep, dest = spec.rpartition(";") if ";" in spec else spec.rpartition(":")
    assert source.replace("\\", "/").endswith("src/cagsyntax/ui/assets")
    assert dest == "cagsyntax/ui/assets"
```

Append to `tests/test_selftest.py`:

```python
def test_the_diagram_image_check_passes_and_is_listed():
    results = selftest.run_selftest()
    row = next(r for r in results if r.name == "Diagram image (artery map)")
    assert row.ok, row.detail
    assert "1200x1200" in row.detail
```

- [ ] **Step 2: Run to see them fail**

Run: `python -m pytest tests/test_packaging_assets.py tests/test_selftest.py -q`
Expected: FAIL (no `--add-data`; no such check).

- [ ] **Step 3: Implement**

In `tools/packaging/build_exe.py`, add `import os` to the imports and, inside `pyinstaller_command`, before `return cmd + [str(ENTRY)]`, add:

```python
    assets = ROOT / "src" / "cagsyntax" / "ui" / "assets"
    cmd += ["--add-data", f"{assets}{os.pathsep}cagsyntax/ui/assets"]      # heart illustration and its licence
```

In `write_readme`, add one line before the final `"Do not copy cases.sqlite ..."` text:

```python
        "Heart illustration in the segment diagram: DBCLS, CC BY 4.0 (modified); see cagsyntax/ui/assets.\n\n"
```

In `src/cagsyntax/selftest.py`, add above `CHECKS`:

```python
def _check_artery_map_image() -> str:
    from PIL import Image
    from .ui.artery_map import IMAGE_PATH
    with Image.open(IMAGE_PATH) as im:
        im.load()
        return f"heart illustration {im.width}x{im.height}"
```

and add to the `CHECKS` tuple, after the `Scoring engine` entry:

```python
    ("Diagram image (artery map)", lambda: _check_artery_map_image()),
```

In `CHANGELOG.md`, under `### New` of `## Unreleased (branch agent-core)`, add as the first bullet:

```markdown
- **Coronary artery diagram.** The scoring panel has a realistic heart illustration beside the stick-figure tree
  (switch: Diagram | Schematic). All 25 segments are clickable on it. Segments that are hidden from the front view
  (circumflex system, posterior descending, posterolateral, left main) are drawn dashed because their position is
  schematic. The illustration is by DBCLS, CC BY 4.0, modified. If its image file is missing, the panel uses the
  Schematic.
```

- [ ] **Step 4: Run the whole suite**

Run: `python -m pytest -q`
Expected: no failures. (6 skips may remain for missing `torch` and ARCADE; the oracle tests pass once `tools/oracle/official/` exists.)

- [ ] **Step 5: Optional packaged-build check, then commit**

If PyInstaller is installed (`pip install pyinstaller`), run `python tools/packaging/build_exe.py` and confirm the report lists `Diagram image (artery map)` as passed. If it is not installed, say so; the build check is not part of the test suite.

```bash
git add tools/packaging/build_exe.py src/cagsyntax/selftest.py CHANGELOG.md tests/test_packaging_assets.py tests/test_selftest.py
git commit -m "Ship the heart illustration in the portable build and check it in the self-test

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Self-review against the spec

- Artwork and licence (credit, licence file, share-alike image excluded): Task 1 and the guard test; credit text on screen in Task 3 (`CREDIT`) and in the portable README in Task 6.
- Components 1 to 4 (`ArteryMap`, `ARTERY_GEO`, panel switch, packaging): Tasks 3, 2, 4, 6.
- Drawing and interaction (fit, tapered paths, theme colours, badges, first-segment ring, dashed hidden segments with legend, dominance filtering, hit tolerance, click toggling, minimum size, disabled state): Tasks 3 and 4 (disabled state is set in `_sync`).
- Position quality and owner review: Task 5.
- Error handling (missing image fallback; unknown ids ignored by the inherited `_normalise`): Tasks 3 and 4.
- Testing (contract tests, table checks, panel test, render check, existing suite): Tasks 2 to 6.
- Spec deviation: the spec said the credit appears in "the app's About text", but the app has no About window. The credit is shown as a caption under the diagram, in `LICENSE-artwork.md`, and in the portable build's README instead.
- Spec deviation: the spec offered either extracting shared selection logic or copying it. The plan uses a third option, subclassing `SegmentTree`, which needs neither.
- Image format: the spec said a downscaled `.webp`; the plan ships a PNG, which Qt loads without an image-format plugin that PyInstaller might omit.
