import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cagsyntax.app import MainWindow, format_summary
from cagsyntax.dicom_import.reader import read_xa
from cagsyntax.viewer.widget import CineWidget
from tests.dicom_factory import DOSE_SR_SOP, make_xa


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_widget_shows_frame_counter_and_steps(qapp, tmp_path):
    w = CineWidget()
    w.set_series(read_xa(make_xa(tmp_path / "a.dcm")), "LAO 30 CRAN 20")
    assert w.frame_label.text() == "frame 1 / 5"
    w.step_fwd_btn.click()
    assert w.frame_label.text() == "frame 2 / 5"
    assert "LAO 30 CRAN 20" in w.view_label.text()


def test_show_frame_pauses_the_cine_and_shows_that_frame(qapp, tmp_path):
    w = CineWidget()
    w.set_series(read_xa(make_xa(tmp_path / "a.dcm")), "x")
    w.play_btn.click()
    assert w.player.playing
    seen = []
    w.frame_changed.connect(seen.append)
    w.show_frame(3)
    assert not w.player.playing and w.play_btn.text() == "Play" and not w._timer.isActive()
    assert w.frame_label.text() == "frame 4 / 5" and w.frame_index() == 3 and seen[-1] == 3
    w.show_frame(99)                                            # out of range: the last frame, never a crash
    assert w.frame_index() == 4


def test_show_frame_with_nothing_shown_does_nothing(qapp):
    CineWidget().show_frame(2)


def test_zoom_is_clamped(qapp, tmp_path):
    w = CineWidget()
    w.set_series(read_xa(make_xa(tmp_path / "a.dcm")), "x")
    for _ in range(50):
        w.zoom_by(1.25)
    assert w.zoom == 8.0
    for _ in range(100):
        w.zoom_by(0.8)
    assert w.zoom == 0.25


def test_play_button_toggles_player(qapp, tmp_path):
    w = CineWidget()
    w.set_series(read_xa(make_xa(tmp_path / "a.dcm")), "x")
    w.play_btn.click()
    assert w.player.playing
    w.play_btn.click()
    assert not w.player.playing


def test_main_window_imports_and_lists(qapp, tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    make_xa(src / "a.dcm")
    make_xa(src / "sr.dcm", sop_class=DOSE_SR_SOP)
    win = MainWindow(tmp_path / "data")
    result = win.import_from(src)
    assert len(result.imported) == 1 and len(result.rejected) == 1
    assert win.item_list.count() == 1
    win.item_list.setCurrentRow(0)
    assert win.cine.frame_label.text() == "frame 1 / 5"


def test_format_summary_lists_rejections_and_warnings(qapp, tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    make_xa(src / "a.dcm", burned_in=True)
    make_xa(src / "sr.dcm", sop_class=DOSE_SR_SOP)
    win = MainWindow(tmp_path / "data")
    text = format_summary(win.import_from(src))
    assert "Imported: 1" in text and "Rejected: 1" in text
    assert "sr.dcm" in text and "burned-in" in text


def test_burned_in_flag_shows_on_row_and_survives_restart(qapp, tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    make_xa(src / "flagged.dcm", burned_in=True)
    make_xa(src / "clean.dcm", primary=-20.0)
    win = MainWindow(tmp_path / "data")
    win.import_from(src)
    texts = [win.item_list.item(i).text() for i in range(win.item_list.count())]
    assert sum("check burned-in text" in t for t in texts) == 1
    reopened = MainWindow(tmp_path / "data")
    texts = [reopened.item_list.item(i).text() for i in range(reopened.item_list.count())]
    assert sum("check burned-in text" in t for t in texts) == 1


def test_startup_lists_stored_series_without_decoding_pixels(qapp, tmp_path, monkeypatch):
    src = tmp_path / "in"
    src.mkdir()
    make_xa(src / "a.dcm", burned_in=True)
    make_xa(src / "b.dcm", primary=-20.0, secondary=10.0)
    MainWindow(tmp_path / "data").import_from(src)

    def no_decode(*a, **k):
        raise AssertionError("startup must not decode pixel data")

    monkeypatch.setattr("cagsyntax.app.read_xa", no_decode)
    reopened = MainWindow(tmp_path / "data")
    texts = [reopened.item_list.item(i).text() for i in range(reopened.item_list.count())]
    assert len(texts) == 2
    assert any("RAO 20 CRAN 10" in t for t in texts)
    assert all("20261120" in t for t in texts)


def test_selecting_a_series_shows_loading_message_while_decoding(qapp, tmp_path, monkeypatch):
    src = tmp_path / "in"
    src.mkdir()
    make_xa(src / "a.dcm")
    win = MainWindow(tmp_path / "data")
    win.import_from(src)
    seen = []
    import cagsyntax.app as appmod
    real = appmod.read_xa

    def spy(path):
        seen.append(win.statusBar().currentMessage())
        return real(path)

    monkeypatch.setattr(appmod, "read_xa", spy)
    win.item_list.setCurrentRow(0)
    assert seen and "Loading" in seen[0]
    assert win.statusBar().currentMessage() == ""
    assert win.cine.frame_label.text() == "frame 1 / 5"


def _two_folders(tmp_path):
    a = tmp_path / "in_a"
    b = tmp_path / "in_b"
    a.mkdir()
    b.mkdir()
    make_xa(a / "a1.dcm")
    make_xa(a / "a2.dcm", primary=-20.0)
    make_xa(b / "b1.dcm", primary=10.0)
    win = MainWindow(tmp_path / "data")
    win.import_from(a, "Case 01")
    win.import_from(b, "Case 02")
    return win, a, b


def _rows(win):
    return [win.item_list.item(i).text() for i in range(win.item_list.count())]


def test_rows_show_folder_name_and_combo_lists_folders(qapp, tmp_path):
    win, _, _ = _two_folders(tmp_path)
    assert sum("[Case 01]" in t for t in _rows(win)) == 2
    assert sum("[Case 02]" in t for t in _rows(win)) == 1
    combo = [win.folder_combo.itemText(i) for i in range(win.folder_combo.count())]
    assert combo == ["All folders", "Case 01", "Case 02"]


def test_folder_combo_filters_the_list(qapp, tmp_path):
    win, _, _ = _two_folders(tmp_path)
    win.folder_combo.setCurrentText("Case 02")
    assert len(_rows(win)) == 1 and "[Case 02]" in _rows(win)[0]
    win.folder_combo.setCurrentText("All folders")
    assert len(_rows(win)) == 3


def test_folder_names_survive_restart(qapp, tmp_path):
    _two_folders(tmp_path)
    reopened = MainWindow(tmp_path / "data")
    assert sum("[Case 01]" in t for t in _rows(reopened)) == 2


def test_reimport_keeps_the_original_folder_name(qapp, tmp_path):
    win, a, _ = _two_folders(tmp_path)
    r = win.import_from(a, "Other name")
    assert len(r.skipped_duplicates) == 2
    assert sum("[Case 01]" in t for t in _rows(win)) == 2
    assert not any("[Other name]" in t for t in _rows(win))


def test_delete_selected_series_after_confirm(qapp, tmp_path):
    win, a, _ = _two_folders(tmp_path)
    win._confirm = lambda text: True
    win.item_list.setCurrentRow(0)
    shown = win.cine.frame_label.text()
    assert shown.startswith("frame 1")
    assert win.delete_selected_series() is True
    assert len(_rows(win)) == 2
    assert len(list((tmp_path / "data" / "store").glob("*.dcm"))) == 2
    assert win.cine.frame_label.text() == "frame 0 / 0"
    assert (a / "a1.dcm").exists() and (a / "a2.dcm").exists()  # originals untouched


def test_delete_series_declined_changes_nothing(qapp, tmp_path):
    win, _, _ = _two_folders(tmp_path)
    win._confirm = lambda text: False
    win.item_list.setCurrentRow(0)
    assert win.delete_selected_series() is False
    assert len(_rows(win)) == 3


def test_delete_folder_removes_only_that_folder(qapp, tmp_path):
    win, a, b = _two_folders(tmp_path)
    win._confirm = lambda text: True
    assert win.delete_folder("Case 01") == 2
    assert len(_rows(win)) == 1 and "[Case 02]" in _rows(win)[0]
    assert [win.folder_combo.itemText(i) for i in range(win.folder_combo.count())] == ["All folders", "Case 02"]
    assert (a / "a1.dcm").exists() and (b / "b1.dcm").exists()


def test_delete_folder_defaults_to_the_selected_rows_folder(qapp, tmp_path):
    win, _, _ = _two_folders(tmp_path)
    win._confirm = lambda text: True
    win.item_list.setCurrentRow(len(_rows(win)) - 1)  # last row is in Case 02
    assert win.delete_folder() == 1


def test_delete_folder_confirmation_names_folder_and_count(qapp, tmp_path):
    win, _, _ = _two_folders(tmp_path)
    asked = []
    win._confirm = lambda text: asked.append(text) or False
    win.delete_folder("Case 01")
    assert "Case 01" in asked[0] and "2" in asked[0] and "original" in asked[0].lower()
    assert len(_rows(win)) == 3


def test_rename_folder_updates_rows_and_combo(qapp, tmp_path):
    win, _, _ = _two_folders(tmp_path)
    assert win.rename_folder("Case 01", "Patient A") == 2
    assert sum("[Patient A]" in t for t in _rows(win)) == 2
    assert [win.folder_combo.itemText(i) for i in range(win.folder_combo.count())] == \
        ["All folders", "Case 02", "Patient A"]


def test_rename_folder_blank_name_is_ignored(qapp, tmp_path):
    win, _, _ = _two_folders(tmp_path)
    assert win.rename_folder("Case 01", "   ") == 0
    assert sum("[Case 01]" in t for t in _rows(win)) == 2


def test_rows_say_cine_or_still_and_cines_come_first(qapp, tmp_path):
    from tests.dicom_factory import SC_SOP
    d = tmp_path / "in"
    d.mkdir()
    make_xa(d / "a_still.dcm", sop_class=SC_SOP)       # sorts first by file name
    make_xa(d / "z_cine.dcm", frames=7)
    win = MainWindow(tmp_path / "data")
    win.import_from(d, "Case 01")
    rows = _rows(win)
    assert "CINE 7 frames" in rows[0]
    assert "STILL" in rows[1]


def test_summary_counts_cines_and_stills(qapp, tmp_path):
    from tests.dicom_factory import SC_SOP
    d = tmp_path / "in"
    d.mkdir()
    make_xa(d / "cine.dcm")
    make_xa(d / "still.dcm", sop_class=SC_SOP)
    text = format_summary(MainWindow(tmp_path / "data").import_from(d))
    assert "Imported: 2" in text and "1 cine" in text and "1 still" in text
