import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cagsyntax.ui import artery_map
from cagsyntax.ui.artery_geo import midpoint
from cagsyntax.ui.artery_map import CANVAS, CAPTION_H
from cagsyntax.ui.scoring_panel import ScoringPanel


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_the_diagram_is_the_default_and_the_switch_changes_the_picker(qapp):
    panel = ScoringPanel()
    assert panel.current_picker() == "diagram"
    assert panel.picker_stack.currentWidget() is panel.map
    panel.show_picker("schematic")
    assert panel.current_picker() == "schematic"
    assert panel.picker_stack.currentWidget() is panel.tree
    assert panel.schematic_button.isChecked() and not panel.diagram_button.isChecked()
    panel.show_picker("diagram")
    assert panel.diagram_button.isChecked()


def test_a_selection_is_shown_on_both_pickers(qapp):
    panel = ScoringPanel()
    panel.set_dominance("right")
    panel.toggle_segment("6")
    assert panel.tree.selected() == ["6"] and panel.map.selected() == ["6"]


def test_clicking_on_the_diagram_edits_the_lesion(qapp):
    panel = ScoringPanel()
    panel.set_dominance("right")
    panel.map.resize(int(CANVAS), int(CANVAS) + CAPTION_H)
    x, y = midpoint("7")
    QTest.mouseClick(panel.map, Qt.MouseButton.LeftButton, pos=QPoint(round(x * CANVAS), round(y * CANVAS)))
    assert panel.case().lesions[0].segments == ["7"]
    assert panel.tree.selected() == ["7"]


def test_a_missing_image_falls_back_to_the_schematic(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(artery_map, "IMAGE_PATH", tmp_path / "missing.png")
    panel = ScoringPanel()
    assert panel.current_picker() == "schematic"
    assert not panel.diagram_button.isEnabled()
    panel.show_picker("diagram")                       # ignored: there is no image
    assert panel.current_picker() == "schematic"


def test_a_short_window_scrolls_the_panel_and_a_tall_one_fills_it(qapp):
    from cagsyntax.ui.scoring_panel import MIN_CONTENT_HEIGHT
    panel = ScoringPanel()
    page = panel.layout().itemAt(0).widget()           # the scroll area that holds the whole panel
    panel.resize(900, 300)
    panel.show()
    qapp.processEvents()
    assert page.widget().height() == MIN_CONTENT_HEIGHT          # too short: the content keeps its height and scrolls
    assert page.verticalScrollBar().maximum() > 0
    panel.resize(900, 900)
    qapp.processEvents()
    assert page.widget().height() == 900                          # tall enough: the content fills the window
    assert page.verticalScrollBar().maximum() == 0
    panel.close()


def test_enlarge_opens_a_second_diagram_that_stays_in_sync(qapp):
    panel = ScoringPanel()
    panel.set_dominance("right")
    assert panel.enlarged_map is None and panel.enlarge_button.isEnabled()
    panel.enlarge_button.click()
    big = panel.enlarged_map
    assert big is not None
    dialog = panel.enlarged_dialog
    assert dialog is not None and dialog.isVisible()
    panel.toggle_segment("6")                                      # change made in the panel shows in the window
    assert big.selected() == ["6"]
    big.resize(int(CANVAS), int(CANVAS) + CAPTION_H)               # a click in the window edits the lesion
    x, y = midpoint("8")
    QTest.mouseClick(big, Qt.MouseButton.LeftButton, pos=QPoint(round(x * CANVAS), round(y * CANVAS)))
    assert panel.case().lesions[0].segments == ["6", "8"]
    assert panel.map.selected() == ["6", "8"] and panel.tree.selected() == ["6", "8"]
    dialog.close()


def test_enlarge_reuses_the_same_window(qapp):
    panel = ScoringPanel()
    panel.enlarge_button.click()
    first = panel.enlarged_dialog
    first.close()
    panel.enlarge_button.click()
    assert panel.enlarged_dialog is first and first.isVisible()
    first.close()


def test_enlarge_is_disabled_without_the_image(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(artery_map, "IMAGE_PATH", tmp_path / "missing.png")
    panel = ScoringPanel()
    assert not panel.enlarge_button.isEnabled()
    panel.open_enlarged()                                          # ignored: there is no image
    assert panel.enlarged_dialog is None
