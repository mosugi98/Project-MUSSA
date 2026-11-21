import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from cagsyntax.app import MainWindow
from cagsyntax.ui import theme as T
from cagsyntax.ui.segment_tree import GEO, SegmentTree
from cagsyntax.ui.widgets import GlossyButton


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def restore(qapp):
    yield
    T.set_theme(T.theme_from_preset("meadow"))
    qapp.setStyleSheet("")


def test_the_window_applies_the_default_green_and_yellow_theme(qapp, tmp_path):
    win = MainWindow(tmp_path / "data")
    th = T.theme_from_preset("meadow")
    sheet = qapp.styleSheet().lower()
    assert T.get_theme() == th and th.primary.lower() in sheet and th.accent.lower() in sheet
    assert win.theme_path == tmp_path / "data" / "theme.json"


def test_a_saved_theme_file_is_loaded_at_startup(qapp, tmp_path):
    (tmp_path / "data").mkdir()
    T.save_theme(T.theme_from_preset("forest").with_changes(radius=20), tmp_path / "data" / "theme.json")
    MainWindow(tmp_path / "data")
    assert T.get_theme().preset == "forest" and T.get_theme().radius == 20
    assert T.theme_from_preset("forest").background.lower() in qapp.styleSheet().lower()


def test_a_damaged_theme_file_falls_back_and_says_so(qapp, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "theme.json").write_text("{broken", encoding="utf-8")
    win = MainWindow(tmp_path / "data")
    assert T.get_theme() == T.theme_from_preset("meadow")
    assert "theme.json" in win.statusBar().currentMessage()


def test_invalid_values_in_the_theme_file_are_reported_but_the_rest_still_applies(qapp, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "theme.json").write_text(json.dumps({"preset": "forest", "primary": "nope", "radius": 18}), encoding="utf-8")
    win = MainWindow(tmp_path / "data")
    assert T.get_theme().radius == 18 and T.get_theme().primary == T.theme_from_preset("forest").primary
    assert "primary" in win.statusBar().currentMessage()


def test_the_toolbar_has_an_appearance_action_that_opens_the_window(qapp, tmp_path):
    win = MainWindow(tmp_path / "data")
    assert any(a.text() == "Appearance" for a in win.findChildren(QAction))
    d = win.open_appearance()
    assert d.isVisible() and d.windowTitle() == "Appearance"
    assert win.open_appearance() is d                           # one window, not a pile of them
    d.close()


def test_the_main_buttons_are_glossy_with_sensible_variants(qapp, tmp_path):
    win = MainWindow(tmp_path / "data")
    assert isinstance(win.save_button, GlossyButton) and win.save_button.variant() == "primary"
    assert isinstance(win.confirm_button, GlossyButton) and win.confirm_button.variant() == "accent"
    assert isinstance(win.cine.play_btn, GlossyButton) and win.cine.play_btn.variant() == "primary"
    assert isinstance(win.cine.step_fwd_btn, GlossyButton)
    assert isinstance(win.panel.option_button("thrombus", True), GlossyButton)
    assert win.panel.option_button("thrombus", True).isCheckable()


def test_the_segment_picker_follows_the_theme(qapp):
    tree = SegmentTree()
    tree.resize(560, 440)
    tree.set_scoring_dominance("right")
    tree.set_selected(["6"])
    x1, y1, x2, y2 = GEO["6"]
    cx, cy = round((x1 + x2) / 2) - 8, round((y1 + y2) / 2)      # inside the numbered circle, beside the digit
    before = tree.grab().toImage().pixelColor(cx, cy).name()
    assert before.lower() == T.get_theme().primary.lower()
    T.set_theme(T.get_theme().with_changes(primary="#0A5A2A"))
    assert tree.grab().toImage().pixelColor(cx, cy).name().lower() == "#0a5a2a"
