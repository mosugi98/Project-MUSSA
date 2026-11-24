import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from cagsyntax.scoring.tables import SEGMENT_IDS, weight
from cagsyntax.ui import theme as T
from cagsyntax.ui.artery_geo import midpoint
from cagsyntax.ui.artery_map import CANVAS, CAPTION_H, ArteryMap
from cagsyntax.ui.segment_tree import SegmentTree


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def mid(seg):
    x, y = midpoint(seg)
    return x * CANVAS, y * CANVAS


@pytest.fixture
def amap(qapp):
    m = ArteryMap()
    m.resize(int(CANVAS), int(CANVAS) + CAPTION_H)       # scale 1, no offset
    m.set_scoring_dominance("right")
    return m


def click(widget, x, y):
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(round(x), round(y)))


def test_it_is_a_segment_picker(amap):
    assert isinstance(amap, SegmentTree)
    assert amap.image_available()


def test_every_applicable_segment_is_hit_at_its_midpoint(amap):
    for dom in ("right", "left"):
        amap.set_scoring_dominance(dom)
        for seg in SEGMENT_IDS:
            expected = seg if weight(seg, dom) is not None else None
            assert amap.segment_at(*mid(seg)) == expected, (dom, seg)


def test_empty_space_and_no_dominance_hit_nothing(amap):
    assert amap.segment_at(5, 5) is None
    amap.set_scoring_dominance(None)
    assert amap.segment_at(*mid("6")) is None


def test_clicking_toggles_and_emits_in_table_order(amap):
    spy = QSignalSpy(amap.selection_changed)
    for seg in ("8", "6"):
        click(amap, *mid(seg))
    assert amap.selected() == ["6", "8"]
    assert spy.count() == 2 and spy.at(1)[0] == ["6", "8"]
    click(amap, *mid("6"))
    assert amap.selected() == ["8"]


def test_clicking_a_segment_that_does_not_exist_for_the_dominance_does_nothing(amap):
    amap.set_scoring_dominance("left")
    spy = QSignalSpy(amap.selection_changed)
    click(amap, *mid("4"))
    assert amap.selected() == [] and spy.count() == 0


def test_hit_testing_scales_with_a_bigger_widget(qapp):
    m = ArteryMap()
    m.set_scoring_dominance("right")
    m.resize(2000, 2000 + CAPTION_H)                       # scale 2
    x, y = mid("6")
    click(m, 2 * x, 2 * y)
    assert m.selected() == ["6"]


def test_hit_testing_centres_the_picture_in_a_wide_widget(qapp):
    m = ArteryMap()
    m.set_scoring_dominance("right")
    m.resize(1400, 700 + CAPTION_H)                        # scale 0.7, picture centred horizontally
    x, y = mid("7")
    click(m, 350 + 0.7 * x, 0.7 * y)
    assert m.selected() == ["7"]


def test_first_segment_marker_and_painting_do_not_crash(amap):
    amap.set_selected(["2", "3"])
    amap.set_first_segment("2")
    assert amap.first_segment() == "2"
    amap.grab()


def test_selected_segments_follow_the_theme(amap):
    amap.set_selected(["6"])
    x, y = mid("6")
    before = amap.grab().toImage().pixelColor(round(x) - 8, round(y)).name()
    assert before.lower() == T.get_theme().primary.lower()
    T.set_theme(T.get_theme().with_changes(primary="#0A5A2A"))
    assert amap.grab().toImage().pixelColor(round(x) - 8, round(y)).name().lower() == "#0a5a2a"


def test_a_missing_image_is_reported_and_painting_still_works(qapp, tmp_path):
    m = ArteryMap(image_path=tmp_path / "nope.png")
    m.resize(500, 500 + CAPTION_H)
    assert not m.image_available()
    m.grab()
