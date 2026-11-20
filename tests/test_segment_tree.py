import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from cagsyntax.scoring.tables import SEGMENT_IDS, weight
from cagsyntax.ui.segment_tree import GEO, SegmentTree


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def mid(seg):
    x1, y1, x2, y2 = GEO[seg]
    return (x1 + x2) / 2, (y1 + y2) / 2


@pytest.fixture
def tree(qapp):
    t = SegmentTree()
    t.resize(560, 440)          # logical canvas size: scale 1, no offset
    t.set_scoring_dominance("right")
    return t


def test_geometry_covers_all_25_segments():
    assert set(GEO) == set(SEGMENT_IDS)


def test_every_applicable_segment_is_hit_at_its_midpoint(tree):
    for dom in ("right", "left"):
        tree.set_scoring_dominance(dom)
        for seg in SEGMENT_IDS:
            expected = seg if weight(seg, dom) is not None else None
            assert tree.segment_at(*mid(seg)) == expected, (dom, seg)


def test_empty_space_and_no_dominance_hit_nothing(tree):
    assert tree.segment_at(5, 5) is None
    tree.set_scoring_dominance(None)
    assert tree.segment_at(*mid("6")) is None


def test_clicking_toggles_and_emits_in_table_order(tree):
    spy = QSignalSpy(tree.selection_changed)
    for seg in ("8", "6"):
        x, y = mid(seg)
        QTest.mouseClick(tree, Qt.MouseButton.LeftButton, pos=QPoint(round(x), round(y)))
    assert tree.selected() == ["6", "8"]                 # table order, not click order
    assert spy.count() == 2 and spy.at(1)[0] == ["6", "8"]
    x, y = mid("6")
    QTest.mouseClick(tree, Qt.MouseButton.LeftButton, pos=QPoint(round(x), round(y)))
    assert tree.selected() == ["8"]


def test_clicking_a_hidden_segment_does_nothing(tree):
    tree.set_scoring_dominance("left")
    spy = QSignalSpy(tree.selection_changed)
    x, y = mid("4")
    QTest.mouseClick(tree, Qt.MouseButton.LeftButton, pos=QPoint(round(x), round(y)))
    assert tree.selected() == [] and spy.count() == 0


def test_set_selected_drops_segments_not_applicable_and_orders_them(tree):
    tree.set_selected(["8", "15", "6", "99"])
    assert tree.selected() == ["6", "8"]


def test_changing_dominance_drops_segments_that_no_longer_exist(tree):
    tree.set_selected(["4", "8"])
    tree.set_scoring_dominance("left")
    assert tree.selected() == ["8"]


def test_widget_scales_hit_testing_with_its_size(qapp):
    t = SegmentTree()
    t.set_scoring_dominance("right")
    t.resize(1120, 880)                                   # scale 2
    x, y = mid("6")
    QTest.mouseClick(t, Qt.MouseButton.LeftButton, pos=QPoint(round(2 * x), round(2 * y)))
    assert t.selected() == ["6"]


def test_first_segment_marker_is_stored_and_paint_does_not_crash(tree):
    tree.set_selected(["2", "3"])
    tree.set_first_segment("2")
    assert tree.first_segment() == "2"
    tree.grab()                                           # renders offscreen without error
