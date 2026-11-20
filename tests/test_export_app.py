import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from cagsyntax.app import MainWindow, format_export_summary
from tests.dicom_factory import SC_SOP
from tests.test_export_dataset import STUDY_A, put
from tests.test_scoring_flow import STUDY, fill_lad, make_source, open_window, select_first


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def confirmed_window(tmp_path, with_still=False, scorer="Dr Secret Name"):
    """A window whose only study (two cines, optionally a still) has a confirmed reference."""
    src = make_source(tmp_path)
    if with_still:
        put(src / "still.dcm", STUDY, sop_class=SC_SOP)
    win = open_window(tmp_path, src)
    win.library.assign([e.uid for e in win.library.entries()], "Patient John Doe case")
    win.refresh_list()
    win.add_user(scorer, "cardiologist")
    select_first(win)
    assert win.score_selected_case()
    fill_lad(win)
    win._confirm = lambda text: True
    assert win.confirm_entry(win.save_entry().id) is not None
    return win


def read(out, name):
    return (out / name).read_text(encoding="utf-8")


def test_export_end_to_end(qapp, tmp_path):
    win = confirmed_window(tmp_path)
    result = win.export_confirmed_cases(tmp_path / "out")
    assert (result.cases, result.series) == (1, 2)
    data = json.loads(read(tmp_path / "out", "dataset.json"))
    assert data["cases"][0]["reference"]["total"] == 7.0 and data["cases"][0]["confirmed_by_level"] == "cardiologist"
    assert "Exported" in win.statusBar().currentMessage() and str(tmp_path / "out") in win.statusBar().currentMessage()


def test_nothing_confirmed_gives_a_clear_message_and_creates_nothing(qapp, tmp_path):
    win = open_window(tmp_path, make_source(tmp_path))
    assert win.export_confirmed_cases(tmp_path / "out") is None
    assert "no confirmed" in win.statusBar().currentMessage().lower()
    assert not (tmp_path / "out").exists()


def test_export_is_unavailable_without_the_case_store(qapp, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "cases.sqlite").write_bytes(b"garbage" * 100)
    win = open_window(tmp_path, make_source(tmp_path))
    assert win.export_confirmed_cases(tmp_path / "out") is None


def test_a_non_empty_target_is_refused_with_a_dialog(qapp, tmp_path):
    win = confirmed_window(tmp_path)
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "mine.txt").write_text("keep")
    warned = []
    win._warn = warned.append
    assert win.export_confirmed_cases(tmp_path / "out") is None
    assert warned and "not empty" in warned[0] and (tmp_path / "out" / "mine.txt").read_text() == "keep"
    assert "Nothing was exported" in win.statusBar().currentMessage()


def test_options_are_passed_through(qapp, tmp_path):
    win = confirmed_window(tmp_path, with_still=True)
    default = win.export_confirmed_cases(tmp_path / "cines_only")
    assert default.series == 2 and not (tmp_path / "cines_only" / "images").exists()
    full = win.export_confirmed_cases(tmp_path / "full", include_stills=True, copy_images=True)
    assert full.series == 3 and full.images_copied == 3
    assert len(list((tmp_path / "full" / "images").glob("*.dcm"))) == 3
    assert json.loads(read(tmp_path / "full", "dataset.json"))["options"] == {"include_stills": True, "images_copied": True}


def test_export_contains_no_scorer_name_folder_label_or_patient_identifier(qapp, tmp_path):
    win = confirmed_window(tmp_path)
    win.export_confirmed_cases(tmp_path / "out", copy_images=True)
    for f in (tmp_path / "out").rglob("*"):
        if f.is_file() and f.suffix != ".dcm":
            text = f.read_text(encoding="utf-8")
            for needle in ("Dr Secret Name", "Secret", "Patient John Doe", "DOE", "JOHN", "MRN12345", STUDY, STUDY_A):
                assert needle not in text, (f.name, needle)


def test_exporting_changes_neither_the_case_store_nor_the_series_list(qapp, tmp_path):
    win = confirmed_window(tmp_path)
    before = (win.store.case_summaries(), win.item_list.count(), win.store.confirmation(win._scoring_study[0]).total)
    win.export_confirmed_cases(tmp_path / "out")
    after = (win.store.case_summaries(), win.item_list.count(), win.store.confirmation(win._scoring_study[0]).total)
    assert before == after


def test_summary_text(qapp, tmp_path):
    from cagsyntax.export.writer import ExportResult
    text = format_export_summary(ExportResult(tmp_path / "out", cases=2, series=5, excluded=1, inconsistent=1, images_copied=0))
    assert "2 case" in text and "5 series" in text and "1 case" in text and "not exported" in text.lower()
    assert "differ" in text.lower() and str(tmp_path / "out") in text


def test_the_toolbar_has_an_export_action(qapp, tmp_path):
    win = open_window(tmp_path)
    assert any(a.text() == "Export dataset" for a in win.findChildren(QAction))
