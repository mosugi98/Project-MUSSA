from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..scoring.tables import SEGMENT_IDS, weight
from . import theme as T

CANVAS_W, CANVAS_H = 560, 440
HIT_RADIUS = 14.0

# Segment id -> (x1, y1, x2, y2) on the 560 x 440 logical canvas (schematic, not anatomical).
GEO = {
    "1": (70, 60, 62, 130), "2": (62, 130, 55, 220), "3": (55, 220, 85, 300), "4": (85, 300, 135, 395),
    "16": (85, 300, 40, 360), "16a": (40, 360, 20, 402), "16b": (40, 360, 46, 412), "16c": (40, 360, 70, 405),
    "5": (300, 40, 300, 95), "6": (300, 95, 345, 150), "7": (345, 150, 375, 240), "8": (375, 240, 385, 340),
    "9": (352, 160, 440, 185), "9a": (440, 185, 500, 205), "10": (378, 250, 450, 285),
    "10a": (450, 285, 505, 310),
    "11": (300, 95, 250, 140), "12": (300, 95, 290, 190), "12a": (250, 140, 185, 165),
    "12b": (242, 190, 180, 225), "13": (250, 140, 235, 240), "14": (235, 240, 220, 310),
    "14a": (220, 310, 195, 355), "14b": (220, 310, 245, 360), "15": (235, 240, 285, 335),
}
LABELS = (("RCA", 20, 40), ("LM", 318, 40), ("LAD / diagonals", 400, 130), ("LCx", 120, 110))


def _distance_to_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    t = 0.0 if length_sq == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


class SegmentTree(QWidget):
    """Schematic coronary tree. Tap a segment to select it; segments that do not exist for the
    scoring dominance are not drawn and cannot be selected."""

    selection_changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        import weakref
        ref = weakref.ref(self)
        token = T.subscribe(lambda _t: ref() and ref().update())
        self.destroyed.connect(lambda *_a, t=token: T.unsubscribe(t))
        self._dominance: str | None = None
        self._selected: list[str] = []
        self._first: str | None = None
        self.setMinimumSize(360, 285)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # ---- state ----
    def _applicable(self, seg: str) -> bool:
        return self._dominance in ("right", "left") and weight(seg, self._dominance) is not None

    def _normalise(self, ids) -> list[str]:
        return [s for s in SEGMENT_IDS if s in set(ids) and self._applicable(s)]

    def set_scoring_dominance(self, dominance: str | None) -> None:
        self._dominance = dominance
        self._selected = self._normalise(self._selected)
        if self._first not in self._selected:
            self._first = None
        self.update()

    def set_selected(self, ids: list[str]) -> None:
        self._selected = self._normalise(ids)
        if self._first not in self._selected:
            self._first = None
        self.update()

    def selected(self) -> list[str]:
        return list(self._selected)

    def set_first_segment(self, seg: str | None) -> None:
        self._first = seg if seg in self._selected else None
        self.update()

    def first_segment(self) -> str | None:
        return self._first

    # ---- geometry ----
    def _scale(self) -> tuple[float, float, float]:
        s = min(self.width() / CANVAS_W, self.height() / CANVAS_H)
        return s, (self.width() - CANVAS_W * s) / 2, (self.height() - CANVAS_H * s) / 2

    def segment_at(self, x: float, y: float) -> str | None:
        """Segment under a point given in logical (560 x 440) canvas coordinates."""
        best, best_d = None, HIT_RADIUS
        for seg in SEGMENT_IDS:
            if not self._applicable(seg):
                continue
            d = _distance_to_segment(x, y, *GEO[seg])
            if d < best_d:
                best, best_d = seg, d
        return best

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        s, ox, oy = self._scale()
        pos = event.position()
        seg = self.segment_at((pos.x() - ox) / s, (pos.y() - oy) / s)
        if seg is None:
            return
        chosen = [x for x in self._selected if x != seg] if seg in self._selected else self._selected + [seg]
        self._selected = self._normalise(chosen)
        if self._first not in self._selected:
            self._first = None
        self.update()
        self.selection_changed.emit(self.selected())

    # ---- painting ----
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        s, ox, oy = self._scale()
        p.translate(ox, oy)
        p.scale(s, s)
        th = T.get_theme()
        accent = QColor(th.primary)
        idle = pal.mid().color()
        font = QFont(self.font())
        font.setPixelSize(10)
        font.setBold(True)
        p.setFont(font)
        p.setPen(pal.placeholderText().color())
        for text, x, y in LABELS:
            p.drawText(QPointF(x, y), text)
        for seg in SEGMENT_IDS:
            if not self._applicable(seg):
                continue
            x1, y1, x2, y2 = GEO[seg]
            on = seg in self._selected
            pen = QPen(accent if on else idle, 10)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            r = 13 if len(seg) > 2 else 11
            ring = QPen(QColor(th.accent) if seg == self._first else (accent if on else idle), 3 if seg == self._first else 2)
            p.setPen(ring)
            p.setBrush(accent if on else QColor(th.surface))
            p.drawEllipse(QPointF(cx, cy), r, r)
            p.setPen(QColor(th.on_primary) if on else QColor(th.text))
            p.drawText(QRectF(cx - r, cy - r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, seg)
        p.end()
