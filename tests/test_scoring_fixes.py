"""Regression tests for the findings of the step 3 final review."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import dataclasses

import pydicom
import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from cagsyntax.app import MainWindow
from cagsyntax.scoring import Case, Lesion, score_case
from cagsyntax.store import StoreError
from tests.dicom_factory import make_xa
from tests.scoring.builders import case, lesion
from tests.test_scoring_flow import STUDY, fill_lad, make_source, open_window, select_first

STUDY_Y = "1.2.3.8"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def make_two_studies(tmp_path):
    """x1, x2 belong to study X; y1 to study Y. Rows are listed in file-name order."""
    src = tmp_path / "in"
    src.mkdir()
    for name, study, angle in (("x1.dcm", STUDY, 30.0), ("x2.dcm", STUDY, -20.0), ("y1.dcm", STUDY_Y, 10.0)):
        p = make_xa(src / name, primary=angle)
        ds = pydicom.dcmread(p)
        ds.StudyInstanceUID = study
        ds.save_as(p)
    return src


def open_case(tmp_path, name="Ana", level="resident", src=None):
    win = open_window(tmp_path, src or make_source(tmp_path))
    user = win.add_user(name, level)
    select_first(win)
    assert win.score_selected_case()
    return win, user


def uid_of(win):
    return win._scoring_study[0]


def other_study_row(win):
    """Index of a listed series that belongs to a different study than the open case. (Row order
    depends on hashed file names, so tests must not assume which row is which study.)"""
    from pathlib import Path
    from cagsyntax.cases import study_of
    for i in range(win.item_list.count()):
        if study_of(Path(win.item_list.item(i).data(0x100)))[0] != uid_of(win):
            return i
    raise AssertionError("no series of another study")


# ---- Critical 1: adding a scorer while a case is open ----
def test_adding_a_scorer_while_a_case_is_open_reloads_the_case_for_the_new_scorer(qapp, tmp_path):
    win, _ana = open_case(tmp_path)
    fill_lad(win)
    win.save_entry()
    win.add_user("Budi", "resident")
    assert win.current_user().name == "Budi"
    assert win.panel.case().lesions[0].segments == []
    assert "Budi" in win.scoring_dock.windowTitle()
    win.save_entry()                                          # Budi's own (empty) draft
    by_name = {e.user.name: e for e in win.store.entries(uid_of(win))}
    assert by_name["Ana"].total == 7.0 and by_name["Budi"].status == "incomplete"


def test_adding_a_scorer_with_unsaved_edits_asks_and_keeps_the_current_scorer_if_declined(qapp, tmp_path):
    win, _ = open_case(tmp_path)
    fill_lad(win)                                             # unsaved
    win._confirm = lambda text: False
    budi = win.add_user("Budi", "resident")
    assert budi is not None                                   # the scorer is added...
    assert win.current_user().name == "Ana"                   # ...but Ana keeps her unsaved form
    assert win.panel.case().lesions[0].segments == ["6"]
    win._confirm = lambda text: True
    win.user_combo.setCurrentIndex(win.user_combo.findData(budi.id))
    assert win.current_user().name == "Budi" and win.panel.case().lesions[0].segments == []


def test_switching_scorer_with_unsaved_edits_is_declinable(qapp, tmp_path):
    win, ana = open_case(tmp_path)
    budi = win.add_user("Budi", "resident")
    win.user_combo.setCurrentIndex(win.user_combo.findData(ana.id))
    fill_lad(win)
    asked = []
    win._confirm = lambda text: asked.append(text) or False
    win.user_combo.setCurrentIndex(win.user_combo.findData(budi.id))
    assert asked and win.current_user().name == "Ana"
    assert win.user_combo.currentData() == ana.id


# ---- Important 1: the case on screen is the case that is saved ----
def test_dock_title_names_the_open_case(qapp, tmp_path):
    win, _ = open_case(tmp_path)
    title = win.scoring_dock.windowTitle()
    assert "Ana" in title and "Unsorted" in title and "20261120" in title


def test_selecting_a_series_of_another_study_never_changes_which_case_is_saved(qapp, tmp_path):
    win, _ = open_case(tmp_path, src=make_two_studies(tmp_path))
    study_x = uid_of(win)
    fill_lad(win)                                             # unsaved edits on X
    win.item_list.setCurrentRow(other_study_row(win))                            # a series of study Y
    assert "still open" in win.statusBar().currentMessage().lower()
    assert uid_of(win) == study_x
    entry = win.save_entry()
    assert entry.study_uid == study_x and entry.total == 7.0


def test_with_no_unsaved_edits_the_form_follows_the_selected_study(qapp, tmp_path):
    win, _ = open_case(tmp_path, src=make_two_studies(tmp_path))
    study_x = uid_of(win)
    win.item_list.setCurrentRow(other_study_row(win))
    assert uid_of(win) != study_x
    assert win.panel.case().lesions[0].segments == []


# ---- Important 2: unsaved edits are not thrown away silently ----
def test_closing_the_window_with_unsaved_edits_asks(qapp, tmp_path):
    win, _ = open_case(tmp_path)
    fill_lad(win)
    win._confirm = lambda text: False
    event = QCloseEvent()
    win.closeEvent(event)
    assert not event.isAccepted()
    win._confirm = lambda text: True
    event = QCloseEvent()
    win.closeEvent(event)
    assert event.isAccepted()


def test_no_prompt_when_nothing_changed(qapp, tmp_path):
    win, _ = open_case(tmp_path)
    win._confirm = lambda text: (_ for _ in ()).throw(AssertionError("should not ask"))
    win.add_user("Budi", "resident")
    assert win.current_user().name == "Budi"


# ---- Important 3: store errors during a session are reported, never hidden ----
def test_a_failed_save_is_reported_loudly_and_not_shown_as_saved(qapp, tmp_path):
    win, _ = open_case(tmp_path)
    fill_lad(win)
    warned = []
    win._warn = warned.append

    def boom(*a, **k):
        raise StoreError("cases.sqlite: disk full. Nothing was changed.")

    win.store.save_entry = boom
    assert win.save_entry() is None
    assert "NOT SAVED" in win.statusBar().currentMessage()
    assert warned and "disk full" in warned[0]
    assert "Saved" not in win.statusBar().currentMessage().replace("NOT SAVED", "")


def test_a_failed_confirmation_is_reported(qapp, tmp_path):
    win, _ = open_case(tmp_path, level="cardiologist")
    fill_lad(win)
    entry = win.save_entry()
    warned = []
    win._warn = warned.append
    win.store.confirm = lambda *a, **k: (_ for _ in ()).throw(StoreError("locked"))
    assert win.confirm_entry(entry.id) is None
    assert warned and "locked" in warned[0]


def test_startup_store_problem_is_shown_in_a_dialog_once_the_window_runs(qapp, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "cases.sqlite").write_bytes(b"garbage" * 100)
    win = open_window(tmp_path)
    warned = []
    win._warn = warned.append
    win.announce_startup_problems()                           # main() schedules this once the window runs
    assert warned and "cases.sqlite" in warned[0]
    healthy = open_window(tmp_path / "other")
    healthy._warn = warned.append
    healthy.announce_startup_problems()
    assert len(warned) == 1                                   # nothing to announce when the store is fine


# ---- Important 4: saved forms that cannot be read ----
def test_an_unreadable_saved_form_is_not_silently_overwritten(qapp, tmp_path):
    win, ana = open_case(tmp_path)
    uid = uid_of(win)
    win.store.save_entry(uid, ana.id, {"bad": 1}, score_case(case(lesion())))
    assert win.score_selected_case()
    assert "could not be read" in win.statusBar().currentMessage()
    assert win.panel.case().lesions[0].segments == []
    win._confirm = lambda text: False
    assert win.save_entry() is None
    assert win.store.entries(uid)[0].form == {"bad": 1}
    win._confirm = lambda text: True
    assert win.save_entry() is not None
    assert "dominance" in win.store.entries(uid)[0].form


def test_an_inconsistent_saved_form_does_not_crash_the_load(qapp, tmp_path):
    win, ana = open_case(tmp_path)
    odd = Case(dominance="right", scoring_dominance=None,
               lesions=[Lesion(segments=["99"], occlusion=True, first_segment="99")], diffuse_segments=["15"])
    win.store.save_entry(uid_of(win), ana.id, dataclasses.asdict(odd), score_case(case(lesion())))
    assert win.score_selected_case() is True
    assert win.panel.case().lesions[0].segments == []         # unknown and inapplicable segments are dropped
    assert win.panel.case().diffuse_segments == []


# ---- Important 5: the reference is the snapshot ----
def test_reference_line_shows_the_confirmed_snapshot_even_after_the_scorer_edits(qapp, tmp_path):
    win, card = open_case(tmp_path, name="Card", level="cardiologist")
    fill_lad(win)
    win.confirm_entry(win.save_entry().id)
    assert "7" in win.reference_label.text() and "Card" in win.reference_label.text()
    win.panel.add_lesion()                                    # makes the form incomplete
    win.save_entry()
    assert "edited since" in win.entries_list_rows()[0].lower()
    assert "7" in win.reference_label.text()


def test_replacing_an_existing_reference_asks_first(qapp, tmp_path):
    win, card1 = open_case(tmp_path, name="Card1", level="cardiologist")
    fill_lad(win)
    first = win.save_entry()
    win.confirm_entry(first.id)
    card2 = win.add_user("Card2", "cardiologist")
    fill_lad(win, extra=[("severe_tortuosity", True)])
    second = win.save_entry()
    asked = []
    win._confirm = lambda text: asked.append(text) or False
    assert win.confirm_entry(second.id) is None
    assert asked and win.store.confirmation(uid_of(win)).entry_id == first.id
    win._confirm = lambda text: True
    assert win.confirm_entry(second.id).total == 9.0
    win._confirm = lambda text: (_ for _ in ()).throw(AssertionError("same entry: no prompt"))
    assert win.confirm_entry(second.id) is not None


def test_confirming_your_own_row_with_unsaved_changes_asks_you_to_save_first(qapp, tmp_path):
    win, _ = open_case(tmp_path, level="cardiologist")
    fill_lad(win)
    win.save_entry()
    win.panel.toggle_diffuse("7")                             # unsaved change
    win.entries_list.setCurrentRow(0)
    assert win.confirm_selected_entry() is None
    assert "save your changes" in win.statusBar().currentMessage().lower()


# ---- Important 6: unreadable stored series ----
def test_unreadable_stored_series_gives_a_message_not_an_exception(qapp, tmp_path):
    win = open_window(tmp_path, make_source(tmp_path))
    win.add_user("Ana", "resident")
    select_first(win)
    path = win.item_list.currentItem().data(0x100)
    from pathlib import Path
    Path(path).write_bytes(b"junk" * 50)
    assert win.score_selected_case() is False
    assert "cannot be read" in win.statusBar().currentMessage().lower()


# ---- color flag on already scored series ----
FLAG_ROLE = 0x102
COLORS = {"reference": "#2e7d32", "not_confirmed": "#ef6c00", "draft": "#78909c"}


def flags(win):
    return [win.item_list.item(i).data(FLAG_ROLE) for i in range(win.item_list.count())]


def texts(win):
    return [win.item_list.item(i).text() for i in range(win.item_list.count())]


def marker_color(item):
    """Colour of the marker dot at the left of the row, and its alpha."""
    c = item.icon().pixmap(14, 14).toImage().pixelColor(7, 7)
    return c.name().lower(), c.alpha()


def study_flags(win, study_uid):
    from pathlib import Path
    from cagsyntax.cases import study_of
    return [win.item_list.item(i).data(FLAG_ROLE) for i in range(win.item_list.count())
            if study_of(Path(win.item_list.item(i).data(0x100)))[0] == study_uid]


def test_unscored_rows_have_no_flag_and_an_invisible_spacer_so_text_stays_aligned(qapp, tmp_path):
    win = open_window(tmp_path, make_source(tmp_path))
    assert set(flags(win)) == {""}
    item = win.item_list.item(0)
    assert not item.icon().isNull() and marker_color(item)[1] == 0      # transparent spacer
    assert "not scored" in item.toolTip().lower()
    assert not any("scored" in t.lower() or "draft" in t.lower() for t in texts(win))


def test_a_draft_only_study_gets_a_grey_blue_marker_with_an_explanation(qapp, tmp_path):
    win, _ = open_case(tmp_path)
    win.panel.set_dominance("right")
    win.panel.toggle_segment("8")                             # incomplete
    win.save_entry()
    assert set(flags(win)) == {"draft"}
    for i in range(win.item_list.count()):
        item = win.item_list.item(i)
        assert marker_color(item) == (COLORS["draft"], 255)
        assert "unfinished" in item.toolTip().lower()
    assert not any("draft" in t.lower() or "scored" in t.lower() for t in texts(win))   # no text after the series name


def test_a_complete_unconfirmed_score_gets_an_orange_marker(qapp, tmp_path):
    win, _ = open_case(tmp_path)
    fill_lad(win)
    win.save_entry()
    assert set(flags(win)) == {"not_confirmed"}
    item = win.item_list.item(0)
    assert marker_color(item) == (COLORS["not_confirmed"], 255)
    assert "no reference" in item.toolTip().lower()
    assert not any("scored" in t.lower() for t in texts(win))


def test_a_confirmed_study_gets_a_green_marker(qapp, tmp_path):
    win, _ = open_case(tmp_path, level="cardiologist")
    fill_lad(win)
    win.confirm_entry(win.save_entry().id)
    assert set(flags(win)) == {"reference"}
    item = win.item_list.item(0)
    assert marker_color(item) == (COLORS["reference"], 255)
    assert "confirmed" in item.toolTip().lower() and "reference" in item.toolTip().lower()
    assert not any("scored" in t.lower() for t in texts(win))


def test_only_the_scored_study_is_flagged(qapp, tmp_path):
    win, _ = open_case(tmp_path, src=make_two_studies(tmp_path))
    study_x = uid_of(win)
    fill_lad(win)
    win.save_entry()
    assert set(study_flags(win, study_x)) == {"not_confirmed"}
    assert "" in flags(win) and flags(win).count("not_confirmed") == len(study_flags(win, study_x))


def test_the_flag_survives_a_restart(qapp, tmp_path):
    win, _ = open_case(tmp_path)
    fill_lad(win)
    win.save_entry()
    win.store.close()
    again = open_window(tmp_path)
    assert set(flags(again)) == {"not_confirmed"}


def test_the_marker_updates_when_a_draft_becomes_complete(qapp, tmp_path):
    win, _ = open_case(tmp_path)
    win.panel.set_dominance("right")
    win.panel.toggle_segment("6")
    win.save_entry()
    assert set(flags(win)) == {"draft"}
    for field, value in [("occlusion", False), ("trifurcation", 0), ("bifurcation", "none"),
                         ("aorto_ostial", False), ("severe_tortuosity", False), ("length_gt20", False),
                         ("heavy_calcification", False), ("thrombus", False)]:
        assert win.panel.answer(field, value), field
    win.save_entry()
    assert set(flags(win)) == {"not_confirmed"}


# ---- confirming from the list: the button must never silently do nothing ----
def test_your_own_saved_score_is_preselected_so_confirm_works_without_clicking_the_list(qapp, tmp_path):
    win, _ = open_case(tmp_path, level="cardiologist")
    fill_lad(win)
    win.save_entry()
    assert win.entries_list.currentRow() == 0
    win._confirm = lambda text: True
    win.confirm_button.click()
    assert set(flags(win)) == {"reference"}
    assert "reference" in win.statusBar().currentMessage().lower()


def test_confirm_says_exactly_what_will_be_confirmed_and_can_be_declined(qapp, tmp_path):
    win, _ = open_case(tmp_path, name="Dr Yogi", level="cardiologist")
    fill_lad(win)
    win.save_entry()
    asked = []
    win._confirm = lambda text: asked.append(text) or False
    assert win.confirm_selected_entry() is None
    assert asked and "Dr Yogi" in asked[0] and "7" in asked[0] and "reference" in asked[0].lower()
    assert win.store.confirmation(uid_of(win)) is None and set(flags(win)) == {"not_confirmed"}


def test_confirm_with_nothing_selected_shows_a_dialog_not_just_a_status_line(qapp, tmp_path):
    win, _ = open_case(tmp_path, level="cardiologist")
    fill_lad(win)
    win.save_entry()
    win.entries_list.setCurrentRow(-1)
    warned = []
    win._warn = warned.append
    assert win.confirm_selected_entry() is None
    assert warned and "select" in warned[0].lower()


def test_a_lone_score_by_someone_else_is_preselected_for_the_cardiologist(qapp, tmp_path):
    src = make_source(tmp_path)
    win, res = open_case(tmp_path, name="Res", level="resident", src=src)
    fill_lad(win)
    win.save_entry()
    card = win.add_user("Card", "cardiologist")
    assert win.current_user().name == "Card"
    assert win.entries_list.count() == 1 and win.entries_list.currentRow() == 0
    win._confirm = lambda text: True
    assert win.confirm_selected_entry().total == 7.0
    assert set(flags(win)) == {"reference"}


def test_the_confirm_button_for_a_resident_explains_why_it_did_nothing(qapp, tmp_path):
    win, _ = open_case(tmp_path, level="resident")
    fill_lad(win)
    win.save_entry()
    warned = []
    win._warn = warned.append
    win._confirm = lambda text: True
    win.confirm_button.click()
    assert warned and "cardiologist" in warned[0].lower()
    assert set(flags(win)) == {"not_confirmed"}
