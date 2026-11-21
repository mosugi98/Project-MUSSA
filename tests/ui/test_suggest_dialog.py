import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cagsyntax.ai.suggest import Suggestion
from cagsyntax.ui.suggest_dialog import SuggestDialog


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def sugg(segment, score=0.8):
    return Suggestion(segment, score, 120, 0.9 if segment else 0.0, (1, 2, 30, 40))


@pytest.fixture
def dialog(qapp):
    d = SuggestDialog([sugg("6", 0.91), sugg(None, 0.7), sugg("11", 0.55)])
    yield d
    d.close()


def test_it_says_these_are_suggestions_and_nothing_is_added_until_pressed(dialog):
    text = dialog.notice_label.text().lower()
    assert "ai suggestion" in text and "not a diagnosis" in text and "tick" in text


def test_every_candidate_is_listed_unticked_with_segment_confidence_and_size(dialog):
    assert dialog.list.count() == 3
    first = dialog.list.item(0)
    assert "segment 6" in first.text() and "91%" in first.text() and "120" in first.text()
    assert first.checkState() == Qt.CheckState.Unchecked
    assert dialog.chosen() == []


def test_an_unplaced_candidate_is_shown_but_cannot_be_ticked(dialog):
    item = dialog.list.item(1)
    assert "not in any outlined segment" in item.text().lower()
    assert not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable)


def test_chosen_returns_the_ticked_suggestions_in_list_order(dialog):
    dialog.list.item(2).setCheckState(Qt.CheckState.Checked)
    dialog.list.item(0).setCheckState(Qt.CheckState.Checked)
    assert [s.segment for s in dialog.chosen()] == ["6", "11"]


def test_the_two_buttons_accept_and_reject_the_dialog(dialog):
    dialog.add_button.click()
    assert dialog.result() == dialog.DialogCode.Accepted
    other = SuggestDialog([sugg("6")])
    other.cancel_button.click()
    assert other.result() == other.DialogCode.Rejected
    other.close()


def test_the_add_button_says_how_many_are_ticked(dialog):
    assert "0" in dialog.add_button.text()
    dialog.list.item(0).setCheckState(Qt.CheckState.Checked)
    assert "1" in dialog.add_button.text()


def test_confidence_is_shown_as_a_rounded_percentage(qapp):
    d = SuggestDialog([sugg("6", 0.996)])
    assert "100%" in d.list.item(0).text()
    d.close()
