"""MUSSA look and feel: a small set of design tokens and the Qt stylesheet built from them.

Pure Python (no Qt) so it can be tested and edited without a window. The user can change a handful of
tokens (the Appearance window or theme.json in the data folder); every other shade is derived from them.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from string import Template

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
LIMITS = {"radius": (4, 24), "gloss": (0, 100), "anim_ms": (0, 400), "font_size": (9, 16)}
COLOR_TOKENS = ("primary", "accent", "background", "surface", "text", "on_primary")
DANGER = "#D64545"

PRESETS: dict[str, dict] = {
    "meadow": {"label": "Meadow (light)", "primary": "#1F7A44", "accent": "#FFC93C", "background": "#F3F7E6",
               "surface": "#FFFFFF", "text": "#18281C", "on_primary": "#FFFFFF"},
    "forest": {"label": "Forest (dark)", "primary": "#2FB36A", "accent": "#FFD24A", "background": "#0E1D14",
               "surface": "#16291D", "text": "#EAF4E6", "on_primary": "#06210F"},
}
DEFAULT_PRESET = "meadow"


# ------------------------------------------------------------------ colour maths
def hex_to_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, int(round(v)))) for v in (r, g, b)))


def mix(a: str, b: str, t: float) -> str:
    """Linear mix: t=0 gives a, t=1 gives b."""
    (r1, g1, b1), (r2, g2, b2) = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex(r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t)


def lighten(color: str, amount: float) -> str:
    return mix(color, "#FFFFFF", amount)


def darken(color: str, amount: float) -> str:
    return mix(color, "#000000", amount)


def luminance(color: str) -> float:
    def channel(v: int) -> float:
        s = v / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in hex_to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio, 1 (none) to 21 (black on white)."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ------------------------------------------------------------------ the theme
@dataclass(frozen=True)
class Theme:
    preset: str = DEFAULT_PRESET
    primary: str = PRESETS[DEFAULT_PRESET]["primary"]
    accent: str = PRESETS[DEFAULT_PRESET]["accent"]
    background: str = PRESETS[DEFAULT_PRESET]["background"]
    surface: str = PRESETS[DEFAULT_PRESET]["surface"]
    text: str = PRESETS[DEFAULT_PRESET]["text"]
    on_primary: str = PRESETS[DEFAULT_PRESET]["on_primary"]
    radius: int = 14          # corner radius in pixels
    gloss: int = 60           # strength of the glossy highlight, 0 (flat) to 100
    anim_ms: int = 180        # length of hover/press/fade transitions, 0 turns animations off
    font_size: int = 10       # points
    font_family: str = "Segoe UI"

    def with_changes(self, **changes) -> "Theme":
        return replace(self, **changes)

    # derived shades: the user never has to pick these
    @property
    def primary_light(self) -> str:
        return lighten(self.primary, 0.20)

    @property
    def primary_dark(self) -> str:
        return darken(self.primary, 0.20)

    @property
    def accent_light(self) -> str:
        return lighten(self.accent, 0.25)

    @property
    def accent_dark(self) -> str:
        return darken(self.accent, 0.15)

    @property
    def on_accent(self) -> str:
        """Readable text colour on the yellow accent: the best-contrast choice of a few candidates."""
        return max((self.text, self.background, "#111111", "#FFFFFF"), key=lambda c: contrast_ratio(c, self.accent))

    @property
    def border(self) -> str:
        return mix(self.primary, self.surface, 0.72)

    @property
    def muted(self) -> str:
        return mix(self.text, self.background, 0.40)

    @property
    def surface_alt(self) -> str:
        return mix(self.surface, self.primary, 0.08)


def theme_from_preset(name: str) -> Theme:
    preset = PRESETS.get(name) or PRESETS[DEFAULT_PRESET]
    key = name if name in PRESETS else DEFAULT_PRESET
    return Theme(preset=key, **{t: preset[t] for t in COLOR_TOKENS})


def contrast_report(theme: Theme) -> list[tuple[str, float, bool]]:
    """(label, ratio, passes WCAG AA 4.5:1) for the pairs that carry text."""
    pairs = [("Text on background", theme.text, theme.background), ("Text on surface", theme.text, theme.surface),
             ("Text on yellow accent", theme.on_accent, theme.accent),
             ("Button text on green", theme.on_primary, theme.primary)]
    return [(label, contrast_ratio(fg, bg), contrast_ratio(fg, bg) >= 4.5) for label, fg, bg in pairs]


# ------------------------------------------------------------------ files
def _validated(data: dict) -> tuple[Theme, list[str]]:
    base = theme_from_preset(str(data.get("preset", DEFAULT_PRESET)))
    problems: list[str] = []
    values: dict = {}
    for token in COLOR_TOKENS:
        if token in data:
            if isinstance(data[token], str) and HEX.match(data[token]):
                values[token] = data[token].upper()
            else:
                problems.append(f"{token}: not a #RRGGBB colour, preset value used")
    for token, (low, high) in LIMITS.items():
        if token in data:
            v = data[token]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                problems.append(f"{token}: not a number, preset value used")
            else:
                values[token] = int(max(low, min(high, v)))
    if isinstance(data.get("font_family"), str) and data["font_family"].strip():
        values["font_family"] = data["font_family"].strip()
    return base.with_changes(**values), problems


def load_theme(path: Path) -> tuple[Theme, str]:
    """Read theme.json. Missing file: the default preset, no message. Unreadable or invalid values:
    the preset's values plus a message saying what was replaced."""
    path = Path(path)
    if not path.exists():
        return theme_from_preset(DEFAULT_PRESET), ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as exc:
        return theme_from_preset(DEFAULT_PRESET), f"{path.name} could not be read ({exc}); using the default look."
    theme, problems = _validated(data)
    return theme, (f"{path.name}: " + "; ".join(problems)) if problems else ""


def save_theme(theme: Theme, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(theme), indent=1), encoding="utf-8")


# ------------------------------------------------------------------ the current theme (shared by all widgets)
_current: Theme = theme_from_preset(DEFAULT_PRESET)
_listeners: dict[int, object] = {}
_next_token = 0
_animation_override: bool | None = None


def get_theme() -> Theme:
    return _current


def set_theme(theme: Theme) -> None:
    global _current
    if theme == _current:
        return
    _current = theme
    for callback in list(_listeners.values()):
        callback(theme)


def subscribe(callback) -> int:
    global _next_token
    _next_token += 1
    _listeners[_next_token] = callback
    return _next_token


def unsubscribe(token: int) -> None:
    _listeners.pop(token, None)


def set_animation_override(value: bool | None) -> None:
    """False forces animations off (tests, headless); True/None follow the theme."""
    global _animation_override
    _animation_override = value


def animation_ms() -> int:
    return 0 if _animation_override is False else int(_current.anim_ms)


# ------------------------------------------------------------------ stylesheet
def gloss_gradient(base: str, gloss: int, vertical: bool = True) -> str:
    """Glossy fill: a lighter top half over the base colour, a slightly darker bottom."""
    g = max(0, min(100, gloss)) / 100.0
    top, upper = lighten(base, 0.30 * g + 0.06), lighten(base, 0.10 * g)
    lower, bottom = darken(base, 0.02), darken(base, 0.12)
    axis = "x1:0, y1:0, x2:0, y2:1" if vertical else "x1:0, y1:0, x2:1, y2:0"
    return (f"qlineargradient({axis}, stop:0 {top}, stop:0.48 {upper}, stop:0.5 {lower}, stop:1 {bottom})")


_QSS = Template("""
* { font-family: "$font"; font-size: ${fs}pt; color: $text; }
QMainWindow, QDialog, QMessageBox { background: $background; }
QLabel { background: transparent; }
QToolBar { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $surface, stop:1 $surface_alt);
  border: none; border-bottom: 1px solid $border; padding: 6px; spacing: 6px; }
QToolBar QLabel { color: $primary; font-weight: 600; }
QToolButton, QPushButton { background: $primary_fill; color: $on_primary; border: 1px solid $primary_dark;
  border-radius: ${r}px; padding: 6px 14px; font-weight: 600; min-height: 20px; }
QToolButton:hover, QPushButton:hover { background: $primary_fill_hover; }
QToolButton:pressed, QPushButton:pressed { background: $primary_dark; padding-top: 7px; }
QToolButton:checked { background: $accent_fill; color: $on_accent; border: 1px solid $accent_dark; }
QToolButton:disabled, QPushButton:disabled { background: $border; color: $muted; border: 1px solid $border; }
QComboBox { background: $surface; border: 1px solid $border; border-radius: ${r}px; padding: 5px 12px; min-height: 22px; }
QComboBox:hover, QComboBox:focus { border: 1px solid $primary; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border; border-radius: ${r2}px;
  selection-background-color: $accent; selection-color: $on_accent; outline: none; padding: 4px; }
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox { background: $surface; border: 1px solid $border;
  border-radius: ${r}px; padding: 5px 10px; selection-background-color: $accent; selection-color: $on_accent; }
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus { border: 1px solid $primary; }
QListWidget { background: $surface; border: 1px solid $border; border-radius: ${r}px; padding: 4px; outline: none; }
QListWidget::item { padding: 7px 9px; border-radius: ${r2}px; margin: 1px 2px; }
QListWidget::item:hover { background: $surface_alt; }
QListWidget::item:selected { background: $accent_fill; color: $on_accent; }
QGroupBox { background: $surface; border: 1px solid $border; border-radius: ${r}px; margin-top: 16px; padding: 10px 8px 8px 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 14px; padding: 0 8px;
  color: $primary; background: $background; border-radius: ${r2}px; }
QGroupBox:disabled { color: $muted; }
QDockWidget { titlebar-close-icon: none; color: $on_primary; }
QDockWidget::title { background: $primary_fill; color: $on_primary; padding: 8px 12px; font-weight: 600;
  border-top-left-radius: ${r}px; border-top-right-radius: ${r}px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: $primary_light; border-radius: 5px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: $primary; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: $primary_light; border-radius: 5px; min-width: 32px; }
QScrollBar::handle:horizontal:hover { background: $primary; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QStatusBar { background: $surface; border-top: 1px solid $border; color: $muted; }
QStatusBar QLabel { color: $muted; }
QSlider::groove:horizontal { height: 8px; background: $border; border-radius: 4px; }
QSlider::sub-page:horizontal { background: $primary; border-radius: 4px; }
QSlider::handle:horizontal { background: $accent_fill; border: 2px solid $primary_dark; width: 16px; height: 16px;
  margin: -6px 0; border-radius: 9px; }
QSplitter::handle { background: $border; width: 3px; }
QSplitter::handle:hover { background: $primary_light; }
QToolTip { background: $surface; color: $text; border: 1px solid $primary; border-radius: ${r2}px; padding: 6px 8px; }
QProgressDialog, QInputDialog { background: $background; }
""")


def build_stylesheet(theme: Theme) -> str:
    """The application stylesheet for a theme (rounded, glossy, green and yellow by default)."""
    return _QSS.substitute(
        font=theme.font_family, fs=theme.font_size, text=theme.text, background=theme.background,
        surface=theme.surface, surface_alt=theme.surface_alt, border=theme.border, muted=theme.muted,
        primary=theme.primary, primary_light=theme.primary_light, primary_dark=theme.primary_dark,
        accent=theme.accent, accent_dark=theme.accent_dark, on_primary=theme.on_primary,
        on_accent=theme.on_accent, r=theme.radius, r2=max(3, theme.radius // 2),
        primary_fill=gloss_gradient(theme.primary, theme.gloss),
        primary_fill_hover=gloss_gradient(lighten(theme.primary, 0.08), theme.gloss),
        accent_fill=gloss_gradient(theme.accent, theme.gloss))
