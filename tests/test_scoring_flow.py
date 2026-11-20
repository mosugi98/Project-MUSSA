import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pydicom
import pytest
from PySide6.QtWidgets import QApplication

from cagsyntax.app import MainWindow
from tests.dicom_factory import make_xa

STUDY = "1.2.3.7"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def make_source(tmp_path):
    """Two series of one study (name DOE^JOHN, MRN12345 inside the files)."""
    src = tmp_path / "in"
    src.mkdir()
    for name, angle in (("a.dcm", 30.0), ("b.dcm", -20.0)):
        p = make_xa(src / name, primary=angle)
        ds = pydicom.dcmread(p)
        ds.StudyInstanceUID = STUDY
        ds.save_as(p)
    return src


def open_window(tmp_path, src=None):
    win = MainWindow(tmp_path / "data")
    if src is not None:
        win.import_from(src)
    return win


def fill_lad(win, extra=None):
    """Right dominance, one lesion on segment 6, everything 'no' (total 7.0)."""
    p = win.panel
    p.set_dominance("right")
    p.toggle_segment("6")
    for field, value in [("occlusion", False), ("trifurcation", 0), ("bifurcation", "none"),
                         ("aorto_ostial", False), ("severe_tortuosity", False), ("length_gt20", False),
                         ("heavy_calcification", False), ("thrombus", False)] + (extra or []):
        assert p.answer(field, value), field


def select_first(win):
    win.item_list.setCurrentRow(0)


def test_scoring_needs_a_user_and_a_selected_series(qapp, tmp_path):
    win = open_window(tmp_path, make_source(tmp_path))
    assert win.score_selected_case() is False                      # nothing selected, no user
    select_first(win)
    assert win.score_selected_case() is False
    assert "scorer" in win.statusBar().currentMessage().lower()
    win.add_user("Dr Ana", "cardiologist")
    assert win.current_user().name == "Dr Ana"
    assert win.score_selected_case() is True
    assert not win.scoring_dock.isHidden()


def test_save_a_score_and_find_it_again_after_restart(qapp, tmp_path):
    src = make_source(tmp_path)
    win = open_window(tmp_path, src)
    win.add_user("Res", "resident")
    select_first(win)
    assert win.score_selected_case()
    fill_lad(win)
    entry = win.save_entry()
    assert entry.status == "complete" and entry.total == 7.0 and entry.user.name == "Res"
    assert len(win.entries_list_rows()) == 1
    win.store.close()
    again = open_window(tmp_path)
    assert again.current_user().name == "Res"                    # remembered
    select_first(again)
    assert again.score_selected_case()
    assert again.panel.case().lesions[0].segments == ["6"]
    assert again.panel.result().total == 7.0


def test_incomplete_scores_can_be_saved_as_drafts(qapp, tmp_path):
    win = open_window(tmp_path, make_source(tmp_path))
    win.add_user("Res", "resident")
    select_first(win)
    win.score_selected_case()
    win.panel.set_dominance("right")
    win.panel.toggle_segment("8")
    entry = win.save_entry()
    assert entry.status == "incomplete" and entry.total is None
    assert "draft" in win.statusBar().currentMessage().lower()


def test_resident_cannot_confirm_cardiologist_can_and_the_row_is_marked(qapp, tmp_path):
    win = open_window(tmp_path, make_source(tmp_path))
    res = win.add_user("Res", "resident")
    card = win.add_user("Card", "cardiologist")
    select_first(win)
    win.user_combo.setCurrentIndex(win.user_combo.findData(res.id))
    win.score_selected_case()
    fill_lad(win)
    res_entry = win.save_entry()
    assert win.confirm_entry(res_entry.id) is None
    assert "cardiologist" in win.statusBar().currentMessage().lower()
    win.user_combo.setCurrentIndex(win.user_combo.findData(card.id))
    win.score_selected_case()
    fill_lad(win)
    card_entry = win.save_entry()
    assert win.confirm_entry(card_entry.id).total == 7.0
    assert all(win.item_list.item(i).data(0x102) == "reference" for i in range(win.item_list.count()))


def test_confirm_selected_entry_uses_the_entries_list(qapp, tmp_path):
    win = open_window(tmp_path, make_source(tmp_path))
    card = win.add_user("Card", "cardiologist")
    select_first(win)
    win.score_selected_case()
    fill_lad(win)
    win.save_entry()
    win.entries_list.setCurrentRow(0)
    win._confirm = lambda text: True
    assert win.confirm_selected_entry() is not None
    assert "reference" in win.entries_list_rows()[0].lower()


def test_disagreement_report_text(qapp, tmp_path):
    win = open_window(tmp_path, make_source(tmp_path))
    res = win.add_user("Res", "resident")
    card = win.add_user("Card", "cardiologist")
    select_first(win)
    win.user_combo.setCurrentIndex(win.user_combo.findData(res.id))
    win.score_selected_case()
    fill_lad(win, extra=[("severe_tortuosity", True)])            # 9.0
    win.save_entry()
    win.user_combo.setCurrentIndex(win.user_combo.findData(card.id))
    win.score_selected_case()
    fill_lad(win)                                                  # 7.0
    win.confirm_entry(win.save_entry().id)
    text = win.show_disagreements()
    assert "resident" in text.lower() and "1 compared" in text and "2" in text


def test_disagreement_report_with_nothing_to_compare(qapp, tmp_path):
    assert "no confirmed" in open_window(tmp_path).show_disagreements().lower()


def test_scores_survive_deleting_and_reimporting_the_series(qapp, tmp_path):
    src = make_source(tmp_path)
    win = open_window(tmp_path, src)
    win.add_user("Res", "resident")
    select_first(win)
    win.score_selected_case()
    fill_lad(win)
    win.save_entry()
    win._confirm = lambda text: True
    assert win.delete_folder("Unsorted") == 2
    assert win.item_list.count() == 0
    win.import_from(src)
    select_first(win)
    assert win.score_selected_case()
    assert win.panel.result().total == 7.0


def test_case_store_holds_no_patient_identifiers(qapp, tmp_path):
    win = open_window(tmp_path, make_source(tmp_path))
    win.add_user("Res", "resident")
    select_first(win)
    win.score_selected_case()
    fill_lad(win)
    win.save_entry()
    win.store.close()
    raw = (tmp_path / "data" / "cases.sqlite").read_bytes()
    for needle in (b"DOE", b"JOHN", b"MRN12345"):
        assert needle not in raw


def test_corrupt_case_store_disables_scoring_but_the_viewer_still_opens(qapp, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "cases.sqlite").write_bytes(b"garbage" * 100)
    win = open_window(tmp_path, make_source(tmp_path))
    assert win.store is None
    assert "cases.sqlite" in win.statusBar().currentMessage()
    assert win.item_list.count() == 2
    select_first(win)
    assert win.score_selected_case() is False
    assert win.add_user("X", "resident") is None


def test_save_without_an_open_case_does_nothing(qapp, tmp_path):
    win = open_window(tmp_path)
    assert win.save_entry() is None and win.confirm_selected_entry() is None
