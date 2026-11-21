import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from cagsyntax.ui import theme as T
from cagsyntax.ui.widgets import GlossyButton, fade_in, install_theme


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def reset_theme():
    T.set_theme(T.theme_from_preset("meadow"))
    T.set_animation_override(False)
    yield
    T.set_theme(T.theme_from_preset("meadow"))
    T.set_animation_override(None)


def luminance_at(img, x, y):
    c = img.pixelColor(x, y)
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()


# ---- the stylesheet is accepted by Qt (Qt silently ignores one it cannot parse) ----
@pytest.mark.parametrize("preset", sorted(T.PRESETS))
def test_stylesheet_parses_without_qt_warnings(qapp, preset):
    messages = []
    previous = qInstallMessageHandler(lambda kind, ctx, msg: messages.append((kind, msg)))
    try:
        qapp.setStyleSheet(T.build_stylesheet(T.theme_from_preset(preset)))
        w = QWidget()
        w.setStyleSheet(T.build_stylesheet(T.theme_from_preset(preset)))   # a widget-level parse reports errors too
        QLabel("x", w).show()
        qapp.processEvents()
    finally:
        qInstallMessageHandler(previous)
        qapp.setStyleSheet("")
    assert [m for _k, m in messages if "parse" in m.lower() or "unknown property" in m.lower()] == []


# ---- GlossyButton ----
def test_button_behaves_like_a_normal_button(qapp):
    b = GlossyButton("Save")
    spy = QSignalSpy(b.clicked)
    b.click()
    assert spy.count() == 1 and b.text() == "Save"
    b.setCheckable(True)
    b.click()
    assert b.isChecked()


def test_variants_are_validated_and_default_to_neutral(qapp):
    b = GlossyButton("x")
    assert b.variant() == "neutral"
    for v in ("primary", "accent", "neutral"):
        b.set_variant(v)
        assert b.variant() == v
    with pytest.raises(ValueError):
        b.set_variant("rainbow")
    assert GlossyButton("x", variant="primary").variant() == "primary"


def render(b, w=140, h=44):
    b.resize(w, h)
    return b.grab().toImage()


def test_gloss_makes_the_top_half_lighter_and_flat_makes_it_even(qapp):
    glossy = GlossyButton("", variant="primary")
    T.set_theme(T.get_theme().with_changes(gloss=100))
    g = render(glossy)
    top_g, bottom_g = luminance_at(g, 14, 9), luminance_at(g, 14, 36)
    T.set_theme(T.get_theme().with_changes(gloss=0))
    f = render(glossy)
    top_f, bottom_f = luminance_at(f, 14, 9), luminance_at(f, 14, 36)
    assert top_g - bottom_g > top_f - bottom_f + 10        # a visible highlight only when gloss is on


def greenish(c):
    return c.green() > c.red() + 25 and c.green() > c.blue() + 10


def test_corners_are_rounded_and_the_radius_setting_matters(qapp):
    install_theme(qapp, T.get_theme())                      # as in the real app: the app stylesheet styles QPushButton too
    b = GlossyButton("", variant="primary")
    T.set_theme(T.get_theme().with_changes(radius=24))
    assert not greenish(render(b).pixelColor(3, 3))        # a big radius cuts the corner: window background shows
    T.set_theme(T.get_theme().with_changes(radius=4))
    assert greenish(render(b).pixelColor(3, 3))            # a small radius leaves the corner painted
    qapp.setStyleSheet("")


def test_variants_use_the_theme_colours(qapp):
    primary, accent = GlossyButton("", variant="primary"), GlossyButton("", variant="accent")
    p, a = render(primary), render(accent)
    pc, ac = p.pixelColor(14, 36), a.pixelColor(14, 36)
    assert pc.green() > pc.red() and pc.green() > pc.blue()              # green
    assert ac.red() > 200 and ac.green() > 150 and ac.blue() < 140        # yellow


def test_checked_neutral_buttons_turn_yellow(qapp):
    b = GlossyButton("", variant="neutral")
    b.setCheckable(True)
    before = render(b).pixelColor(14, 36)
    b.setChecked(True)
    after = render(b).pixelColor(14, 36)
    assert after.red() > 200 and after.blue() < 140 and (after.red(), after.green(), after.blue()) != (before.red(), before.green(), before.blue())


def test_a_theme_change_repaints_existing_buttons(qapp):
    b = GlossyButton("", variant="primary")
    before = render(b).pixelColor(14, 36).name()
    T.set_theme(T.theme_from_preset("forest"))
    assert render(b).pixelColor(14, 36).name() != before


def test_disabled_buttons_look_faded(qapp):
    from PySide6.QtGui import QColor
    parent = QWidget()                                       # a light window behind the button, as in the app
    parent.setAutoFillBackground(True)
    pal = parent.palette()
    pal.setColor(parent.backgroundRole(), QColor("#F3F7E6"))
    parent.setPalette(pal)
    b = GlossyButton("", parent, variant="primary")
    parent.resize(140, 44)
    b.resize(140, 44)
    on = luminance_at(parent.grab().toImage(), 14, 36)
    b.setEnabled(False)
    assert luminance_at(parent.grab().toImage(), 14, 36) > on + 15      # blended towards the light window


def test_hover_and_press_are_animated_smoothly_when_animations_are_on(qapp):
    T.set_animation_override(True)
    T.set_theme(T.get_theme().with_changes(anim_ms=400))      # long, so a slow or busy machine still sees the middle
    b = GlossyButton("x")
    assert b.hover_progress == 0.0
    b.animate_hover(True)
    seen_between = False
    for _ in range(40):
        QTest.qWait(10)
        if 0.0 < b.hover_progress < 1.0:
            seen_between = True
            break
    assert seen_between                                       # a real transition, not a jump
    QTest.qWait(900)
    assert b.hover_progress == 1.0
    b.animate_hover(False)
    QTest.qWait(900)
    assert b.hover_progress == 0.0


def test_no_animation_means_immediate_changes(qapp):
    b = GlossyButton("x")                                    # override is False in this fixture
    b.animate_hover(True)
    assert b.hover_progress == 1.0
    b.animate_hover(False)
    assert b.hover_progress == 0.0


def test_the_theme_animation_speed_of_zero_turns_animation_off(qapp):
    T.set_animation_override(True)
    T.set_theme(T.get_theme().with_changes(anim_ms=0))
    b = GlossyButton("x")
    b.animate_hover(True)
    assert b.hover_progress == 1.0


def test_buttons_ask_for_a_comfortable_size_so_layouts_do_not_squash_them(qapp):
    b = GlossyButton("Save score")
    hint = b.sizeHint()
    assert hint.height() >= 32                                # touch-friendly height
    assert hint.width() >= b.fontMetrics().horizontalAdvance("Save score") + 24
    assert b.minimumSizeHint().height() >= 32
    assert GlossyButton("<").sizeHint().width() >= 36         # short labels still get a usable target


# ---- fade_in ----
def test_fade_in_runs_and_cleans_up_when_animations_are_on(qapp):
    T.set_animation_override(True)
    T.set_theme(T.get_theme().with_changes(anim_ms=80))
    w = QWidget()
    w.show()
    fade_in(w)
    assert w.graphicsEffect() is not None
    QTest.qWait(300)
    assert w.graphicsEffect() is None                       # no leftover effect that could slow painting


def test_fade_in_does_nothing_when_animations_are_off(qapp):
    w = QWidget()
    fade_in(w)
    assert w.graphicsEffect() is None
    fade_in(None)                                            # tolerated


# ---- applying the theme to the whole application ----
def test_install_theme_sets_the_application_stylesheet_and_follows_later_changes(qapp):
    install_theme(qapp, T.theme_from_preset("meadow"))
    assert T.theme_from_preset("meadow").primary.lower() in qapp.styleSheet().lower()
    T.set_theme(T.theme_from_preset("forest"))
    assert T.theme_from_preset("forest").background.lower() in qapp.styleSheet().lower()
    qapp.setStyleSheet("")


def test_headless_platform_turns_animations_off(qapp):
    T.set_animation_override(None)
    install_theme(qapp, T.theme_from_preset("meadow"))
    assert qapp.platformName() == "offscreen" and T.animation_ms() == 0
    qapp.setStyleSheet("")
