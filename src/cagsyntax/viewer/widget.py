from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPen, QPixmap
from PySide6.QtWidgets import (QGraphicsPixmapItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView,
                               QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget)

from ..dicom_import.models import XASeries
from ..ui.widgets import GlossyButton
from .player import CinePlayer

MIN_ZOOM, MAX_ZOOM = 0.25, 8.0
AI_CAPTION = "AI suggestion - not a diagnosis"   # always drawn with an AI overlay


def to_qimages(frames: np.ndarray) -> list[QImage]:
    """Window-level a series to 8-bit using its own min/max."""
    lo, hi = float(frames.min()), float(frames.max())
    scale = 255.0 / (hi - lo) if hi > lo else 0.0
    images = []
    for f in frames:
        u8 = np.ascontiguousarray(((f.astype(np.float32) - lo) * scale).astype(np.uint8))
        h, w = u8.shape
        images.append(QImage(u8.data, w, h, w, QImage.Format.Format_Grayscale8).copy())
    return images


class _View(QGraphicsView):
    def __init__(self, on_zoom):
        super().__init__()
        self._on_zoom = on_zoom
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(Qt.GlobalColor.black)

    def wheelEvent(self, event):
        self._on_zoom(1.25 if event.angleDelta().y() > 0 else 0.8)


class CineWidget(QWidget):
    frame_changed = Signal(int)          # emitted whenever the shown frame changes (and on pause)

    def __init__(self):
        super().__init__()
        self.player: CinePlayer | None = None
        self._frames: np.ndarray | None = None       # original pixel data of the series
        self._overlay_items: list = []
        self._caption_text = ""
        self.zoom = 1.0
        self._images: list[QImage] = []
        self._scene = QGraphicsScene()
        self._item = QGraphicsPixmapItem()
        self._scene.addItem(self._item)
        self.view = _View(self.zoom_by)
        self.view.setScene(self._scene)
        self.view_label = QLabel("No series loaded")
        self.frame_label = QLabel("frame 0 / 0")
        self.back_btn = GlossyButton("<")
        self.play_btn = GlossyButton("Play", variant="primary")
        self.step_fwd_btn = GlossyButton(">")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        controls = QHBoxLayout()
        for w in (self.back_btn, self.play_btn, self.step_fwd_btn, self.slider, self.frame_label):
            controls.addWidget(w)
        controls.setStretchFactor(self.slider, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.view_label)
        layout.addWidget(self.view, 1)
        layout.addLayout(controls)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self.back_btn.clicked.connect(lambda: self._step(-1))
        self.step_fwd_btn.clicked.connect(lambda: self._step(1))
        self.play_btn.clicked.connect(self._toggle_play)
        self.slider.valueChanged.connect(self._on_slider)

    def set_series(self, series: XASeries, view_label: str) -> None:
        self._timer.stop()
        self._images = to_qimages(series.frames)
        self._frames = series.frames
        self.player = CinePlayer(len(self._images), series.fps)
        self.play_btn.setText("Play")
        self.view_label.setText(view_label)
        self.slider.blockSignals(True)
        self.slider.setRange(0, len(self._images) - 1)
        self.slider.blockSignals(False)
        self.zoom = 1.0
        self._apply_zoom()
        self._show_frame()

    def clear(self) -> None:
        """Forget the current series (e.g. after it was deleted)."""
        self._timer.stop()
        self.clear_overlay()
        self.player = None
        self._images = []
        self._frames = None
        self._item.setPixmap(QPixmap())
        self.play_btn.setText("Play")
        self.view_label.setText("No series loaded")
        self.frame_label.setText("frame 0 / 0")
        self.slider.blockSignals(True)
        self.slider.setRange(0, 0)
        self.slider.blockSignals(False)

    def zoom_by(self, factor: float) -> None:
        self.zoom = min(MAX_ZOOM, max(MIN_ZOOM, self.zoom * factor))
        self._apply_zoom()

    def _apply_zoom(self) -> None:
        self.view.resetTransform()
        self.view.scale(self.zoom, self.zoom)

    def _show_frame(self) -> None:
        p = self.player
        self.clear_overlay()                 # an overlay belongs to one frame
        self._item.setPixmap(QPixmap.fromImage(self._images[p.index]))
        self._scene.setSceneRect(self._item.boundingRect())
        self.frame_label.setText(f"frame {p.index + 1} / {len(self._images)}")
        self.slider.blockSignals(True)
        self.slider.setValue(p.index)
        self.slider.blockSignals(False)
        self.frame_changed.emit(p.index)

    def _step(self, delta: int) -> None:
        if self.player:
            self.player.step(delta)
            self._show_frame()

    def _on_slider(self, value: int) -> None:
        if self.player:
            self.player.seek(value)
            self._show_frame()

    def _toggle_play(self) -> None:
        if not self.player:
            return
        self.player.toggle()
        self.play_btn.setText("Pause" if self.player.playing else "Play")
        if self.player.playing:
            self.clear_overlay()             # no overlay while the cine plays
            self._timer.start(self.player.interval_ms)
        else:
            self._timer.stop()
            self.frame_changed.emit(self.player.index)    # paused: the window may refresh the overlay

    def show_frame(self, index: int) -> None:
        """Pause and show one frame (the evidence jump of an AI proposal). An index out of range is clamped."""
        if not self.player:
            return
        self.player.pause()
        self._timer.stop()
        self.play_btn.setText("Play")
        self.player.seek(index)
        self._show_frame()

    def _on_tick(self) -> None:
        self.player.tick()
        self._show_frame()

    # ---- original frame data and the AI overlay ----
    def current_frame(self) -> np.ndarray | None:
        """The original (not window-levelled) pixel data of the shown frame."""
        if self._frames is None or self.player is None:
            return None
        return self._frames[self.player.index]

    def frame_index(self) -> int:
        return self.player.index if self.player else -1

    def set_overlay(self, rgba: np.ndarray | None, labels: list | None = None, caption: str = "") -> None:
        """Draw an RGBA overlay (same size as the frame) with segment labels. The caption
        "AI suggestion - not a diagnosis" is always drawn with it; a caller cannot replace it."""
        self.clear_overlay()
        if rgba is None:
            return
        height, width = rgba.shape[:2]
        data = np.ascontiguousarray(rgba)
        image = QImage(data.data, width, height, 4 * width, QImage.Format.Format_RGBA8888).copy()
        overlay = QGraphicsPixmapItem(QPixmap.fromImage(image))
        overlay.setZValue(1)
        self._scene.addItem(overlay)
        self._overlay_items.append(overlay)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(10, height // 40))
        for name, x, y in labels or []:
            text = QGraphicsSimpleTextItem(name)
            text.setFont(font)
            text.setBrush(QColor("white"))
            text.setPen(QPen(QColor("black"), 1))
            rect = text.boundingRect()
            text.setPos(x - rect.width() / 2, y - rect.height() / 2)
            text.setZValue(2)
            self._scene.addItem(text)
            self._overlay_items.append(text)
        banner = QGraphicsSimpleTextItem(AI_CAPTION)
        banner_font = QFont()
        banner_font.setBold(True)
        banner_font.setPixelSize(max(12, height // 32))
        banner.setFont(banner_font)
        banner.setBrush(QColor("#ffd54f"))
        banner.setPen(QPen(QColor("black"), 1))
        banner.setPos(6, 4)
        banner.setZValue(3)
        self._scene.addItem(banner)
        self._overlay_items.append(banner)
        self._caption_text = AI_CAPTION

    def clear_overlay(self) -> None:
        for item in self._overlay_items:
            self._scene.removeItem(item)
        self._overlay_items = []
        self._caption_text = ""

    def overlay_visible(self) -> bool:
        return bool(self._overlay_items)

    def overlay_caption(self) -> str:
        return self._caption_text
