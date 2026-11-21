"""Glossy, rounded, smoothly animated building blocks for the MUSSA look."""
from __future__ import annotations

import weakref

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QPushButton, QWidget

from . import theme as T

VARIANTS = ("neutral", "primary", "accent")


class GlossyButton(QPushButton):
    """A QPushButton that paints itself: rounded corners, a glossy highlight on the top half and a
    smooth fade between its resting, hover and pressed looks. Variants: "neutral" (white, turns
    yellow when checked), "primary" (green) and "accent" (yellow). All colours come from the theme."""

    def __init__(self, text: str = "", parent=None, variant: str = "neutral"):
        super().__init__(text, parent)
        self._variant = "neutral"
        self.set_variant(variant)
        self._hover = 0.0
        self._press = 0.0
        self._animations: dict[str, QPropertyAnimation] = {}
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # the app stylesheet styles every QPushButton; this button paints itself, so keep that box invisible
        self.setStyleSheet("background: transparent; border: none; padding: 0; min-height: 0;")
        ref = weakref.ref(self)

        def repaint(_theme) -> None:
            button = ref()
            if button is not None:
                try:
                    button.update()
                except RuntimeError:           # the C++ object is already gone
                    pass

        token = T.subscribe(repaint)
        self.destroyed.connect(lambda *_a, t=token: T.unsubscribe(t))

    def sizeHint(self) -> QSize:
        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold)
        from PySide6.QtGui import QFontMetrics
        width = QFontMetrics(font).horizontalAdvance(self.text())
        return QSize(max(38, width + 32), max(34, QFontMetrics(font).height() + 16))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # ---- variant ----
    def variant(self) -> str:
        return self._variant

    def set_variant(self, variant: str) -> None:
        if variant not in VARIANTS:
            raise ValueError(f"Unknown button variant {variant!r}; use one of {', '.join(VARIANTS)}.")
        self._variant = variant
        self.update()

    # ---- animated state (0..1) ----
    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    def _get_press(self) -> float:
        return self._press

    def _set_press(self, value: float) -> None:
        self._press = float(value)
        self.update()

    hover_progress = Property(float, _get_hover, _set_hover)
    press_progress = Property(float, _get_press, _set_press)

    def _animate(self, name: str, end: float) -> None:
        ms = T.animation_ms()
        setter = self._set_hover if name == "hover_progress" else self._set_press
        running = self._animations.get(name)
        if running is not None:
            running.stop()
        if ms <= 0:
            setter(end)
            return
        anim = QPropertyAnimation(self, name.encode(), self)
        anim.setDuration(ms)
        anim.setStartValue(self._hover if name == "hover_progress" else self._press)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animations[name] = anim
        anim.start()

    def animate_hover(self, on: bool) -> None:
        self._animate("hover_progress", 1.0 if on else 0.0)

    def enterEvent(self, event) -> None:
        self.animate_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.animate_hover(False)
        self._animate("press_progress", 0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._animate("press_progress", 1.0)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._animate("press_progress", 0.0)
        super().mouseReleaseEvent(event)

    # ---- painting ----
    def _palette_for_state(self, th: T.Theme) -> tuple[str, str, str, str]:
        """(top colour, bottom colour, border colour, text colour)."""
        kind = "accent" if (self.isCheckable() and self.isChecked()) else self._variant
        if kind == "primary":
            return th.primary_light, th.primary_dark, th.primary_dark, th.on_primary
        if kind == "accent":
            return th.accent_light, th.accent_dark, th.accent_dark, th.on_accent
        return th.surface, th.surface_alt, th.border, th.text

    def paintEvent(self, _event) -> None:
        th = T.get_theme()
        top, bottom, border, text = self._palette_for_state(th)
        hover, press = self._hover, self._press
        top, bottom = T.mix(top, "#FFFFFF", 0.14 * hover), T.mix(bottom, "#FFFFFF", 0.10 * hover)
        top, bottom = T.mix(top, "#000000", 0.14 * press), T.mix(bottom, "#000000", 0.14 * press)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.45)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        radius = min(float(th.radius), rect.height() / 2.0)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        if press > 0:
            p.translate(0, 1.0 * press)
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fill.setColorAt(0.0, QColor(top))
        fill.setColorAt(1.0, QColor(bottom))
        p.fillPath(path, fill)
        gloss = th.gloss / 100.0
        if gloss > 0:
            # the glossy highlight: a bright cap over the top half that fades towards the middle
            cap = QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.52)
            shine = QLinearGradient(cap.topLeft(), cap.bottomLeft())
            shine.setColorAt(0.0, QColor(255, 255, 255, int(150 * gloss)))
            shine.setColorAt(1.0, QColor(255, 255, 255, int(28 * gloss)))
            p.save()
            p.setClipPath(path)
            p.fillRect(cap, shine)
            p.restore()
        p.setPen(QPen(QColor(border), 1.2))
        p.drawPath(path)
        if self.hasFocus():
            ring = QPainterPath()
            ring.addRoundedRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5), radius, radius)
            p.setPen(QPen(QColor(th.accent), 2.0))
            p.drawPath(ring)
        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor(text))
        label = p.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, int(rect.width() - 16))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        p.end()


def fade_in(widget: QWidget | None, ms: int | None = None) -> None:
    """Fade a widget in. Does nothing when animations are off; removes its effect when finished so
    it cannot slow painting."""
    duration = T.animation_ms() if ms is None else ms
    if widget is None or duration <= 0:
        return
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def done() -> None:
        try:
            widget.setGraphicsEffect(None)
        except RuntimeError:
            pass

    anim.finished.connect(done)
    widget._fade_animation = anim              # keep a reference alive until it finishes
    anim.start()


def _apply_sheet(app: QApplication, theme: T.Theme) -> None:
    """Setting an application stylesheet re-styles every widget, so skip it when nothing changed."""
    sheet = T.build_stylesheet(theme)
    if app.styleSheet() != sheet:
        app.setStyleSheet(sheet)


def install_theme(app: QApplication, theme: T.Theme) -> None:
    """Make `theme` the current theme and keep the application stylesheet in step with it."""
    if app.platformName() == "offscreen":
        T.set_animation_override(False)         # headless runs (tests) never animate
    T.set_theme(theme)
    _apply_sheet(app, theme)
    if not app.property("mussa_theme_token"):
        token = T.subscribe(lambda th: _apply_sheet(app, th))
        app.setProperty("mussa_theme_token", token)
