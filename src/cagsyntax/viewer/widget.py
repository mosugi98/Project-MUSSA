from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout,
                               QLabel, QPushButton, QSlider, QVBoxLayout, QWidget)

from ..dicom_import.models import XASeries
from .player import CinePlayer

MIN_ZOOM, MAX_ZOOM = 0.25, 8.0


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
    def __init__(self):
        super().__init__()
        self.player: CinePlayer | None = None
        self.zoom = 1.0
        self._images: list[QImage] = []
        self._scene = QGraphicsScene()
        self._item = QGraphicsPixmapItem()
        self._scene.addItem(self._item)
        self.view = _View(self.zoom_by)
        self.view.setScene(self._scene)
        self.view_label = QLabel("No series loaded")
        self.frame_label = QLabel("frame 0 / 0")
        self.back_btn = QPushButton("<")
        self.play_btn = QPushButton("Play")
        self.step_fwd_btn = QPushButton(">")
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
        self.player = CinePlayer(len(self._images), series.fps)
        self.play_btn.setText("Play")
        self.view_label.setText(view_label)
        self.slider.blockSignals(True)
        self.slider.setRange(0, len(self._images) - 1)
        self.slider.blockSignals(False)
        self.zoom = 1.0
        self._apply_zoom()
        self._show_frame()

    def zoom_by(self, factor: float) -> None:
        self.zoom = min(MAX_ZOOM, max(MIN_ZOOM, self.zoom * factor))
        self._apply_zoom()

    def _apply_zoom(self) -> None:
        self.view.resetTransform()
        self.view.scale(self.zoom, self.zoom)

    def _show_frame(self) -> None:
        p = self.player
        self._item.setPixmap(QPixmap.fromImage(self._images[p.index]))
        self._scene.setSceneRect(self._item.boundingRect())
        self.frame_label.setText(f"frame {p.index + 1} / {len(self._images)}")
        self.slider.blockSignals(True)
        self.slider.setValue(p.index)
        self.slider.blockSignals(False)

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
            self._timer.start(self.player.interval_ms)
        else:
            self._timer.stop()

    def _on_tick(self) -> None:
        self.player.tick()
        self._show_frame()
