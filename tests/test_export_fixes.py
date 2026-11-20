"""Regression tests for the findings of the step 4 final review."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import csv
import dataclasses
import json
import re
from pathlib import Path

import numpy as np
import pydicom
import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from cagsyntax.cases import study_of
from cagsyntax.dicom_import.importer import import_path
from cagsyntax.export.dataset import build_dataset
from cagsyntax.export.splits import suggest_split
from cagsyntax.export.writer import ExportCancelled, write_export
from cagsyntax.library import Library
from cagsyntax.scoring import score_case
from cagsyntax.store import CaseStore
from tests.dicom_factory import make_xa
from tests.scoring.builders import case, lesion
from tests.test_export_build import confirm
from tests.test_export_dataset import STUDY_A, STUDY_B, put
from tests.test_scoring_flow import make_source, open_window, select_first
from tests.test_export_app import confirmed_window

SALT = b"s" * 32
PLANTED = ["Budi", "Santoso", "Dr Andi", "teacher", "063Y", "101530", "Pasien"]


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def planted_world(tmp_path, burned_in=False, mrn="MRN12345"):
    src = tmp_path / "in"
    src.mkdir()
    p = put(src / "a.dcm", STUDY_A, primary=30.0, secondary=20.0, frames=6, burned_in=burned_in, mrn=mrn)
    ds = pydicom.dcmread(p)
    ds.SeriesDescription = "Pasien Budi Santoso LAD"
    ds.StudyDescription = "Study for Budi Santoso"
    ds.ProtocolName = "Dr Andi protocol"
    ds.Occupation = "teacher"
    ds.PatientSex = "M"
    ds.PatientAge = "063Y"
    ds.StudyTime = "101530"
    ds.save_as(p)
    import_path(src, tmp_path / "data" / "store", SALT)
    lib = Library(tmp_path / "data")
    store = CaseStore(tmp_path / "data" / "cases.sqlite")
    return lib, store, study_of(lib.entries()[0].path)[0]


# ---- Important 1: copied headers carry only what the export promises ----
def test_copied_dicom_headers_keep_only_an_allow_list(tmp_path):
    lib, store, uid = planted_world(tmp_path)
    confirm(store, uid, mrn_hash="hash-1")
    ds = build_dataset(store, lib)
    write_export(ds, lib, tmp_path / "out", copy_images=True)
    copied = next((tmp_path / "out" / "images").glob("*.dcm"))
    raw = copied.read_bytes()
    for needle in PLANTED:
        assert needle.encode() not in raw, needle
    original = pydicom.dcmread(lib.store_dir / copied.name)
    again = pydicom.dcmread(copied)
    for kw in ("PatientSex", "PatientAge", "StudyTime", "SeriesDescription", "StudyDescription",
               "ProtocolName", "Occupation"):
        assert kw not in again, kw
    assert str(again.get("PatientName", "")) == ""
    assert (again.Modality, again.StudyDate, again.NumberOfFrames) == ("XA", "20261120", 6)
    assert again.PatientID == original.PatientID                       # the salted MRN hash
    assert again.SOPInstanceUID == original.SOPInstanceUID and again.StudyInstanceUID == original.StudyInstanceUID
    assert (again.PositionerPrimaryAngle, again.PositionerSecondaryAngle) == (30.0, 20.0)
    assert again.FrameTime == original.FrameTime and again.BurnedInAnnotation == original.BurnedInAnnotation
    assert np.array_equal(again.pixel_array, original.pixel_array)
    assert again.file_meta.TransferSyntaxUID == original.file_meta.TransferSyntaxUID
    assert not any(e.tag.is_private for e in again)
    store.close()


# ---- Important 2: the reference holds only the confirmed data ----
def test_reference_lesions_are_the_confirmed_form_and_the_breakdown_is_the_current_engines(tmp_path):
    lib, store, uid = planted_world(tmp_path)
    confirm(store, uid, mrn_hash="hash-1", form_case=case(lesion(segments=["7"]), diffuse=["8"]))
    store._con.execute("UPDATE confirmations SET total = 99.0, grp = 'high'")
    store._con.commit()
    c = build_dataset(store, lib).cases[0]
    assert c.reference["total"] == 99.0 and c.reference["lesions"] == [{"segments": ["7"]}]
    assert c.reference["diffuse_segments"] == ["8"]
    assert c.rescored["consistent"] is False and c.rescored["total"] == 5.0 + 1.0 and c.rescored["diffuse_points"] == 1
    assert c.rescored["lesions"][0]["total"] == 5.0
    assert "total" not in c.reference["lesions"][0]
    store.close()


def test_a_form_the_current_engine_rejects_keeps_its_reference_and_has_an_empty_breakdown(tmp_path):
    lib, store, uid = planted_world(tmp_path)
    confirm(store, uid, mrn_hash="hash-1")
    bad = dataclasses.asdict(case(lesion(segments=["15"])))             # segment 15 does not exist for right dominance
    store._con.execute("UPDATE confirmations SET form_json = ?", (json.dumps(bad),))
    store._con.commit()
    c = build_dataset(store, lib).cases[0]
    assert c.reference["total"] == 5.0 and c.reference["lesions"] == [{"segments": ["15"]}]
    assert c.rescored["total"] is None and c.rescored["consistent"] is False and c.rescored["lesions"] == []
    store.close()


# ---- Important 3: no MRN means no shared patient key ----
def test_cases_without_an_mrn_get_no_patient_key_and_are_split_individually(tmp_path):
    lib, store, uid = planted_world(tmp_path)
    confirm(store, uid, mrn_hash="")
    ds = build_dataset(store, lib)
    c = ds.cases[0]
    assert c.patient_key is None and c.suggested_split == suggest_split(uid)
    write_export(ds, lib, tmp_path / "out")
    data = json.loads((tmp_path / "out" / "dataset.json").read_text(encoding="utf-8"))
    assert data["cases"][0]["patient_key"] is None and data["counts"]["without_patient_key"] == 1
    rows = list(csv.reader(open(tmp_path / "out" / "cases.csv", newline="", encoding="utf-8")))
    assert dict(zip(rows[0], rows[1]))["patient_key"] == ""
    assert "no patient key" in (tmp_path / "out" / "README.txt").read_text(encoding="utf-8").lower()
    store.close()


# ---- Important 4: progress, cancel and leftover temp folders ----
def test_progress_is_reported_and_cancel_leaves_nothing_behind(tmp_path):
    lib, store, uid = planted_world(tmp_path)
    put(tmp_path / "in" / "b.dcm", STUDY_A, primary=-20.0)
    import_path(tmp_path / "in", lib.store_dir, SALT)
    confirm(store, uid, mrn_hash="hash-1")
    ds = build_dataset(store, lib)
    seen = []
    write_export(ds, lib, tmp_path / "ok", copy_images=True, progress=lambda done, total: seen.append((done, total)) or True)
    assert seen == [(1, 2), (2, 2)]
    calls = []

    def cancel_after_first(done, total):
        calls.append(done)
        return done < 1

    with pytest.raises(ExportCancelled):
        write_export(ds, lib, tmp_path / "cancelled", copy_images=True, progress=cancel_after_first)
    assert calls == [1] and not (tmp_path / "cancelled").exists() and list(tmp_path.glob("cancelled*")) == []
    store.close()


def test_stale_temp_folders_of_a_killed_export_are_cleaned_up_but_foreign_ones_are_not(tmp_path):
    lib, store, uid = planted_world(tmp_path)
    confirm(store, uid, mrn_hash="hash-1")
    stale = tmp_path / "out.tmp-deadbeef"
    stale.mkdir()
    (stale / ".mussa-export-tmp").write_text("x")
    (stale / "half.dcm").write_bytes(b"partial")
    foreign = tmp_path / "out.tmp-cafebabe"
    foreign.mkdir()
    (foreign / "mine.txt").write_text("not ours")
    write_export(build_dataset(store, lib), lib, tmp_path / "out")
    assert not stale.exists() and (foreign / "mine.txt").exists()
    store.close()


def test_the_parent_folder_must_exist_and_is_not_created(tmp_path):
    lib, store, uid = planted_world(tmp_path)
    confirm(store, uid, mrn_hash="hash-1")
    with pytest.raises(FileNotFoundError, match="does not exist"):
        write_export(build_dataset(store, lib), lib, tmp_path / "nope" / "out")
    assert not (tmp_path / "nope").exists()
    store.close()


# ---- Important 5: the burned-in warning travels with the export ----
def test_burned_in_flag_is_exported_and_warned_about(tmp_path):
    lib, store, uid = planted_world(tmp_path, burned_in=True)
    confirm(store, uid, mrn_hash="hash-1")
    ds = build_dataset(store, lib)
    assert ds.cases[0].series[0].burned_in_unclear is True
    write_export(ds, lib, tmp_path / "out")
    data = json.loads((tmp_path / "out" / "dataset.json").read_text(encoding="utf-8"))
    assert data["cases"][0]["series"][0]["burned_in_unclear"] is True and data["counts"]["burned_in_unclear"] == 1
    assert "burned-in" in (tmp_path / "out" / "README.txt").read_text(encoding="utf-8").lower()
    rows = list(csv.reader(open(tmp_path / "out" / "series.csv", newline="", encoding="utf-8")))
    assert dict(zip(rows[0], rows[1]))["burned_in_unclear"] == "True"
    store.close()


def test_series_stated_to_have_no_burned_in_text_are_not_flagged(tmp_path):
    lib, store, uid = planted_world(tmp_path, burned_in=False)
    confirm(store, uid, mrn_hash="hash-1")
    ds = build_dataset(store, lib)
    assert ds.cases[0].series[0].burned_in_unclear is False
    write_export(ds, lib, tmp_path / "out")
    assert "burned-in" not in (tmp_path / "out" / "README.txt").read_text(encoding="utf-8").lower()
    store.close()


# ---- minors ----
def test_a_damaged_confirmed_form_is_excluded_not_a_crash(tmp_path):
    lib, store, uid = planted_world(tmp_path)
    confirm(store, uid, mrn_hash="hash-1")
    store._con.execute("UPDATE confirmations SET form_json = ?",
                       (json.dumps({"dominance": "right", "scoring_dominance": None, "lesions": [{"segments": 7}]}),))
    store._con.commit()
    ds = build_dataset(store, lib)
    assert ds.cases == [] and "form" in ds.excluded[0].reason.lower()
    store.close()


def test_a_missing_store_file_names_the_series_and_case(tmp_path):
    lib, store, uid = planted_world(tmp_path)
    confirm(store, uid, mrn_hash="hash-1")
    ds = build_dataset(store, lib)
    series_id = ds.cases[0].series[0].series_id
    (lib.store_dir / f"{series_id}.dcm").unlink()
    with pytest.raises(FileNotFoundError) as exc:
        write_export(ds, lib, tmp_path / "out", copy_images=True)
    assert series_id in str(exc.value) and "missing from the store" in str(exc.value)
    assert list(tmp_path.glob("out*")) == []
    store.close()


def test_readme_says_incomplete_or_invalid_instead_of_none(tmp_path):
    lib, store, uid = planted_world(tmp_path)
    confirm(store, uid, mrn_hash="hash-1")
    bad = dataclasses.asdict(case(lesion(segments=["15"])))
    store._con.execute("UPDATE confirmations SET form_json = ?", (json.dumps(bad),))
    store._con.commit()
    write_export(build_dataset(store, lib), lib, tmp_path / "out")
    readme = (tmp_path / "out" / "README.txt").read_text(encoding="utf-8")
    assert "None" not in readme and "incomplete or invalid" in readme
    store.close()


def test_dates_are_rounded_to_the_day(tmp_path):
    lib, store, uid = planted_world(tmp_path)
    confirm(store, uid, mrn_hash="hash-1")
    ds = build_dataset(store, lib)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds.created) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds.cases[0].confirmed_at)
    store.close()


def test_the_exported_form_is_normalised(tmp_path):
    lib, store, uid = planted_world(tmp_path)
    confirm(store, uid, mrn_hash="hash-1")
    form = dataclasses.asdict(case(lesion(segments=["7"])))
    form["note"] = "John Doe called"
    store._con.execute("UPDATE confirmations SET form_json = ?", (json.dumps(form),))
    store._con.commit()
    ds = build_dataset(store, lib)
    text = json.dumps(dataclasses.asdict(ds))
    assert "note" not in ds.cases[0].reference["form"] and "John Doe" not in text
    store.close()


# ---- the Export action: cancel at every step, name sanitising, early target check ----
def stub_dialogs(monkeypatch, win, parent, name="exported", answers=(False, False)):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(parent) if parent else "")
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (name, bool(name)))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    queue = list(answers)
    win._ask_yes_no_cancel = lambda text: queue.pop(0)


def test_export_action_runs_with_the_chosen_options(qapp, tmp_path, monkeypatch):
    win = confirmed_window(tmp_path)
    stub_dialogs(monkeypatch, win, tmp_path, "my export", answers=(False, True))
    win._ask_export()
    assert (tmp_path / "my export" / "dataset.json").exists() and (tmp_path / "my export" / "images").exists()


def test_cancelling_at_any_step_exports_nothing(qapp, tmp_path, monkeypatch):
    win = confirmed_window(tmp_path)
    for parent, name, answers in ((None, "x", ()), (tmp_path, "", ()), (tmp_path, "x", (None,)), (tmp_path, "x", (False, None))):
        stub_dialogs(monkeypatch, win, parent, name, answers)
        win._ask_export()
        assert not (tmp_path / "x").exists()


def test_a_taken_target_name_is_refused_before_any_question_is_asked(qapp, tmp_path, monkeypatch):
    win = confirmed_window(tmp_path)
    (tmp_path / "taken").mkdir()
    (tmp_path / "taken" / "mine.txt").write_text("keep")
    warned = []
    win._warn = warned.append
    stub_dialogs(monkeypatch, win, tmp_path, "taken", answers=())          # any question would raise IndexError
    win._ask_export()
    assert warned and (tmp_path / "taken" / "mine.txt").read_text() == "keep"


def test_the_folder_name_cannot_escape_the_chosen_folder(qapp, tmp_path, monkeypatch):
    win = confirmed_window(tmp_path)
    (tmp_path / "parent").mkdir()
    stub_dialogs(monkeypatch, win, tmp_path / "parent", "..\\..\\escaped", answers=(False, False))
    win._ask_export()
    assert (tmp_path / "parent" / "escaped" / "dataset.json").exists() and not (tmp_path / "escaped").exists()
