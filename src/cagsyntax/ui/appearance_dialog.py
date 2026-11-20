from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QSlider, QVBoxLayout)

from . import theme as T
from .widgets import GlossyButton

COLOR_LABELS = {
    "primary": "Main green", "accent": "Yellow accent", "background": "Window background",
    "surface": "Cards and lists", "text": "Text", "on_primary": "Text on green buttons",
}
SLIDERS = (  # token, label, unit
    ("radius", "Roundness of corners", "px"), ("gloss", "Gloss (shine on buttons)", "%"),
    ("anim_ms", "Animation speed (0 = off)", "ms"), ("font_size", "Text size", "pt"),
)


class AppearanceDialog(QDialog):
    """Live design editor: every change is applied to the whole app at once. Save keeps it in
    theme.json; Undo returns to how it looked when this window opened."""

    def __init__(self, theme_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Appearance")
        self.theme_path = Path(theme_path)
        self._initial = T.get_theme()
        self._building = False
        self.color_buttons: dict[str, GlossyButton] = {}
        self._swatches: dict[str, QLabel] = {}
        self._sliders: dict[str, QSlider] = {}
        self._value_labels: dict[str, QLabel] = {}
        root = QVBoxLayout(self)

        start = QGroupBox("Starting point")
        row = QHBoxLayout(start)
        self.preset_combo = QComboBox()
        for name, data in T.PRESETS.items():
            self.preset_combo.addItem(data["label"], name)
        self.preset_combo.currentIndexChanged.connect(self._on_preset)
        row.addWidget(self.preset_combo, 1)
        root.addWidget(start)

        colors = QGroupBox("Colors  (click a color to change it)")
        grid = QGridLayout(colors)
        for r, (token, label) in enumerate(COLOR_LABELS.items()):
            swatch = QLabel()
            swatch.setFixedSize(26, 26)
            button = GlossyButton("", variant="neutral")
            button.setMinimumWidth(110)
            button.clicked.connect(lambda _c=False, t=token: self.pick_color(t))
            grid.addWidget(QLabel(label), r, 0)
            grid.addWidget(swatch, r, 1)
            grid.addWidget(button, r, 2)
            self._swatches[token], self.color_buttons[token] = swatch, button
        root.addWidget(colors)

        shape = QGroupBox("Shape and feel")
        sg = QGridLayout(shape)
        for r, (token, label, unit) in enumerate(SLIDERS):
            low, high = T.LIMITS[token]
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(low, high)
            if token == "anim_ms":
                slider.setSingleStep(20)
            value = QLabel()
            value.setMinimumWidth(64)
            slider.valueChanged.connect(lambda v, t=token: self._on_slider(t, v))
            sg.addWidget(QLabel(label), r, 0)
            sg.addWidget(slider, r, 1)
            sg.addWidget(value, r, 2)
            self._sliders[token], self._value_labels[token] = slider, value
        root.addWidget(shape)
        self.radius_slider = self._sliders["radius"]
        self.gloss_slider = self._sliders["gloss"]
        self.anim_slider = self._sliders["anim_ms"]
        self.font_slider = self._sliders["font_size"]

        read =QGroupBox("Readability (WCAG contrast; aim for 4.5:1 or more)")
        rl = QVBoxLayout(read)
        self.contrast_label = QLabel()
        self.contrast_label.setWordWrap(True)
        rl.addWidget(self.contrast_label)
        root.addWidget(read)

        self.status_label = QLabel("Changes show immediately. Save keeps them for next time.")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        buttons = QHBoxLayout()
        self.save_button = GlossyButton("Save", variant="primary")
        self.revert_button = GlossyButton("Undo changes")
        self.reset_button = GlossyButton("Reset to preset")
        self.close_button = GlossyButton("Close", variant="accent")
        self.save_button.clicked.connect(lambda _c=False: self.save())
        self.revert_button.clicked.connect(lambda _c=False: self.revert())
        self.reset_button.clicked.connect(lambda _c=False: self.reset_to_preset())
        self.close_button.clicked.connect(self.close)
        for b in (self.save_button, self.revert_button, self.reset_button, self.close_button):
            buttons.addWidget(b)
        root.addLayout(buttons)
        self._sync_from_theme()

    # ---- state ----
    def _apply(self, theme: T.Theme) -> None:
        T.set_theme(theme)
        self._sync_from_theme()

    def _sync_from_theme(self) -> None:
        th = T.get_theme()
        self._building = True
        try:
            self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(th.preset)))
            for token, slider in self._sliders.items():
                slider.setValue(getattr(th, token))
                unit = next(u for t, _l, u in SLIDERS if t == token)
                self._value_labels[token].setText(f"{getattr(th, token)} {unit}")
            for token, button in self.color_buttons.items():
                value = getattr(th, token)
                button.setText(value.upper())
                self._swatches[token].setStyleSheet(
                    f"background: {value}; border: 1px solid {th.border}; border-radius: 7px;")
        finally:
            self._building = False
        lines = []
        for label, ratio, ok in T.contrast_report(th):
            lines.append(f"OK    {label}: {ratio:.1f}:1" if ok
                         else f"Low   {label}: {ratio:.1f}:1 - hard to read, try a stronger color")
        self.contrast_label.setText("\n".join(lines))

    def _on_slider(self, token: str, value: int) -> None:
        if not self._building:
            self._apply(T.get_theme().with_changes(**{token: int(value)}))

    def _on_preset(self, _index: int) -> None:
        if self._building:
            return
        name = self.preset_combo.currentData()
        preset = T.theme_from_preset(name)
        self._apply(T.get_theme().with_changes(preset=name, **{t: getattr(preset, t) for t in T.COLOR_TOKENS}))

    # ---- actions ----
    def set_color(self, token: str, value: str) -> bool:
        if token not in T.COLOR_TOKENS or not isinstance(value, str) or not T.HEX.match(value):
            return False
        self._apply(T.get_theme().with_changes(**{token: value.upper()}))
        return True

    def pick_color(self, token: str) -> None:
        chosen = QColorDialog.getColor(QColor(getattr(T.get_theme(), token)), self, COLOR_LABELS[token])
        if chosen.isValid():
            self.set_color(token, chosen.name().upper())

    def save(self) -> None:
        T.save_theme(T.get_theme(), self.theme_path)
        self.status_label.setText(f"Saved to {self.theme_path}. It will be used the next time you start MUSSA.")

    def reset_to_preset(self) -> None:
        self._apply(T.theme_from_preset(T.get_theme().preset))
        self.status_label.setText("Back to the preset's defaults (not saved yet).")

    def revert(self) -> None:
        self._apply(self._initial)
        self.status_label.setText("Back to how it looked when this window opened.")
