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
