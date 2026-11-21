import json
import re

import pytest

from cagsyntax.ui import theme as T


def test_presets_cover_green_and_yellow_and_every_token_is_a_valid_hex_colour():
    assert {"meadow", "forest"} <= set(T.PRESETS)
    for name in T.PRESETS:
        th = T.theme_from_preset(name)
        for token in ("primary", "accent", "background", "surface", "text", "on_primary"):
            assert T.HEX.match(getattr(th, token)), (name, token)
        assert th.preset == name


def test_default_preset_is_a_light_green_and_yellow_theme_with_readable_text():
    th = T.theme_from_preset("meadow")
    r, g, b = T.hex_to_rgb(th.primary)
    assert g > r and g > b                                   # green
    r, g, b = T.hex_to_rgb(th.accent)
    assert r > 200 and g > 150 and b < 120                   # yellow
    assert T.contrast_ratio(th.text, th.background) >= 7
    assert T.contrast_ratio(th.on_primary, th.primary) >= 4.5
    assert T.contrast_ratio(th.text, th.accent) >= 4.5      # dark text on the yellow accent


def test_every_preset_passes_the_accessibility_contrast_checks():
    for name in T.PRESETS:
        th = T.theme_from_preset(name)
        assert all(ok for _label, _ratio, ok in T.contrast_report(th)), name


def test_contrast_ratio_known_values():
    assert T.contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert T.contrast_ratio("#777777", "#777777") == pytest.approx(1.0)
    assert T.contrast_ratio("#FFFFFF", "#000000") == pytest.approx(21.0)         # order does not matter


def test_contrast_report_flags_a_low_contrast_choice():
    th = T.theme_from_preset("meadow")
    bad = th.with_changes(text="#C8D8B0")                    # pale text on a pale background
    report = {label: ok for label, _ratio, ok in T.contrast_report(bad)}
    assert report["Text on background"] is False


def test_shades_are_derived_and_ordered():
    th = T.theme_from_preset("meadow")
    assert T.luminance(th.primary_light) > T.luminance(th.primary) > T.luminance(th.primary_dark)
    assert T.luminance(th.accent_light) > T.luminance(th.accent) > T.luminance(th.accent_dark)
    for c in (th.border, th.muted, th.surface_alt):
        assert T.HEX.match(c)


def test_mix_lighten_darken():
    assert T.mix("#000000", "#FFFFFF", 0.5).lower() == "#808080"
    assert T.lighten("#204020", 0.2) != "#204020" and T.luminance(T.lighten("#204020", 0.2)) > T.luminance("#204020")
    assert T.luminance(T.darken("#80C080", 0.2)) < T.luminance("#80C080")
    assert T.lighten("#FFFFFF", 0.3).upper() == "#FFFFFF"


def test_load_theme_missing_file_gives_the_default_without_a_message(tmp_path):
    th, msg = T.load_theme(tmp_path / "theme.json")
    assert th == T.theme_from_preset("meadow") and msg == ""


def test_save_and_load_round_trip(tmp_path):
    th = T.theme_from_preset("forest").with_changes(radius=20, gloss=90, anim_ms=300, primary="#1B8F4A")
    path = tmp_path / "theme.json"
    T.save_theme(th, path)
    loaded, msg = T.load_theme(path)
    assert loaded == th and msg == ""
    assert json.loads(path.read_text(encoding="utf-8"))["radius"] == 20


def test_a_corrupt_theme_file_falls_back_to_the_default_with_a_message(tmp_path):
    path = tmp_path / "theme.json"
    path.write_text("{not json", encoding="utf-8")
    th, msg = T.load_theme(path)
    assert th == T.theme_from_preset("meadow") and "theme.json" in msg


def test_bad_values_are_replaced_by_the_presets_and_numbers_are_clamped(tmp_path):
    path = tmp_path / "theme.json"
    path.write_text(json.dumps({"preset": "forest", "primary": "green", "accent": "#12", "radius": 500,
                                "gloss": -5, "anim_ms": "fast", "font_size": 99, "unknown": 1}), encoding="utf-8")
    th, msg = T.load_theme(path)
    forest = T.theme_from_preset("forest")
    assert th.primary == forest.primary and th.accent == forest.accent
    assert th.radius == T.LIMITS["radius"][1] and th.gloss == T.LIMITS["gloss"][0]
    assert th.anim_ms == forest.anim_ms and th.font_size == T.LIMITS["font_size"][1]
    assert "primary" in msg and "accent" in msg


def test_unknown_preset_name_uses_the_default_preset(tmp_path):
    path = tmp_path / "theme.json"
    path.write_text(json.dumps({"preset": "neon"}), encoding="utf-8")
    assert T.load_theme(path)[0].preset == "meadow"


def test_stylesheet_uses_the_tokens_and_the_radius():
    th = T.theme_from_preset("meadow").with_changes(radius=18)
    qss = T.build_stylesheet(th)
    for color in (th.primary, th.accent, th.background, th.surface, th.text):
        assert color.lower() in qss.lower(), color
    assert "border-radius: 18px" in qss and "qlineargradient" in qss
    assert not re.search(r"\{\w+\}", qss)                    # no unformatted placeholders left


def test_stylesheet_changes_when_a_token_changes():
    a = T.build_stylesheet(T.theme_from_preset("meadow"))
    b = T.build_stylesheet(T.theme_from_preset("meadow").with_changes(primary="#0A5A2A"))
    assert a != b


def test_current_theme_listeners_are_called_on_change_and_can_be_removed():
    seen = []
    token = T.subscribe(seen.append)
    new = T.theme_from_preset("forest")
    T.set_theme(new)
    assert seen == [new] and T.get_theme() is new
    T.unsubscribe(token)
    T.set_theme(T.theme_from_preset("meadow"))
    assert seen == [new]


def test_animation_ms_is_zero_when_disabled_by_the_theme_or_the_override():
    th = T.theme_from_preset("meadow").with_changes(anim_ms=200)
    T.set_theme(th)
    T.set_animation_override(True)
    assert T.animation_ms() == 200
    T.set_theme(th.with_changes(anim_ms=0))
    assert T.animation_ms() == 0
    T.set_theme(th)
    T.set_animation_override(False)
    assert T.animation_ms() == 0
    T.set_animation_override(None)
    T.set_theme(T.theme_from_preset("meadow"))
