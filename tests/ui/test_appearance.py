import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QColorDialog

from cagsyntax.ui import theme as T
from cagsyntax.ui.appearance_dialog import AppearanceDialog
from cagsyntax.ui.widgets import install_theme


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(qapp, tmp_path):
    install_theme(qapp, T.theme_from_preset("meadow"))
    d = AppearanceDialog(tmp_path / "theme.json")
    yield d
    d.close()
    T.set_theme(T.theme_from_preset("meadow"))
    qapp.setStyleSheet("")


def test_dialog_opens_with_the_current_theme(dialog):
    th = T.get_theme()
    assert dialog.radius_slider.value() == th.radius and dialog.gloss_slider.value() == th.gloss
    assert dialog.anim_slider.value() == th.anim_ms and dialog.font_slider.value() == th.font_size
    assert dialog.preset_combo.currentData() == th.preset
    assert set(dialog.color_buttons) == {"primary", "accent", "background", "surface", "text", "on_primary"}
    assert dialog.color_buttons["primary"].text().upper() == th.primary


def test_sliders_change_the_look_live(dialog, qapp):
    dialog.radius_slider.setValue(20)
    assert T.get_theme().radius == 20 and "border-radius: 20px" in qapp.styleSheet()
    dialog.gloss_slider.setValue(5)
    assert T.get_theme().gloss == 5
    dialog.anim_slider.setValue(0)
    assert T.get_theme().anim_ms == 0
    dialog.font_slider.setValue(12)
    assert T.get_theme().font_size == 12 and "12pt" in qapp.styleSheet()


def test_set_color_validates_and_applies(dialog, qapp):
    assert dialog.set_color("primary", "#0A5A2A") is True
    assert T.get_theme().primary == "#0A5A2A" and "#0a5a2a" in qapp.styleSheet().lower()
    assert dialog.color_buttons["primary"].text().upper() == "#0A5A2A"
    assert dialog.set_color("primary", "green") is False and T.get_theme().primary == "#0A5A2A"
    assert dialog.set_color("sparkle", "#112233") is False


def test_picking_a_colour_with_the_colour_dialog(dialog, monkeypatch):
    monkeypatch.setattr(QColorDialog, "getColor", lambda *a, **k: QColor("#E6B800"))
    dialog.pick_color("accent")
    assert T.get_theme().accent == "#E6B800"
    monkeypatch.setattr(QColorDialog, "getColor", lambda *a, **k: QColor())      # cancelled: an invalid colour
    dialog.pick_color("accent")
    assert T.get_theme().accent == "#E6B800"


def test_contrast_guidance_warns_about_hard_to_read_choices(dialog):
    assert "hard to read" not in dialog.contrast_label.text().lower()
    dialog.set_color("text", "#C8D8B0")                      # pale text on a pale background
    text = dialog.contrast_label.text()
    assert "hard to read" in text.lower() and "Text on background" in text
    dialog.set_color("text", "#18281C")
    assert "hard to read" not in dialog.contrast_label.text().lower()


def test_changing_the_preset_loads_its_colours_but_keeps_your_shape_settings(dialog):
    dialog.radius_slider.setValue(20)
    dialog.preset_combo.setCurrentIndex(dialog.preset_combo.findData("forest"))
    th = T.get_theme()
    assert th.primary == T.theme_from_preset("forest").primary and th.background == T.theme_from_preset("forest").background
    assert th.radius == 20 and th.preset == "forest"


def test_save_writes_theme_json_and_it_loads_back(dialog, tmp_path):
    dialog.radius_slider.setValue(18)
    dialog.set_color("accent", "#FFD700")
    dialog.save()
    saved = json.loads((tmp_path / "theme.json").read_text(encoding="utf-8"))
    assert saved["radius"] == 18 and saved["accent"] == "#FFD700"
    assert T.load_theme(tmp_path / "theme.json")[0] == T.get_theme()
    assert "theme.json" in dialog.status_label.text()


def test_reset_returns_to_the_presets_defaults(dialog):
    dialog.radius_slider.setValue(20)
    dialog.set_color("primary", "#0A5A2A")
    dialog.reset_to_preset()
    assert T.get_theme() == T.theme_from_preset("meadow")
    assert dialog.radius_slider.value() == T.theme_from_preset("meadow").radius


def test_revert_goes_back_to_how_it_looked_when_the_window_opened(dialog):
    before = T.get_theme()
    dialog.radius_slider.setValue(22)
    dialog.set_color("primary", "#0A5A2A")
    dialog.revert()
    assert T.get_theme() == before and dialog.radius_slider.value() == before.radius


def test_closing_without_saving_keeps_the_live_look_but_writes_nothing(dialog, tmp_path):
    dialog.radius_slider.setValue(21)
    dialog.close()
    assert T.get_theme().radius == 21 and not (tmp_path / "theme.json").exists()
