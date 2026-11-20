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
