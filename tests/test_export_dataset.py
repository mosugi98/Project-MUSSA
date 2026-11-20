import dataclasses
import json
from pathlib import Path

import pydicom
import pytest

from cagsyntax.cases import study_of
from cagsyntax.dicom_import.importer import import_path
from cagsyntax.export.dataset import ExportSeries, series_by_study
from cagsyntax.library import Library
from tests.dicom_factory import SC_SOP, make_xa

SALT = b"s" * 32
STUDY_A, STUDY_B = "1.2.3.1", "1.2.3.2"


def put(path, study, **kw):
    p = make_xa(path, **kw)
    ds = pydicom.dcmread(p)
    ds.StudyInstanceUID = study
    ds.save_as(p)
    return p


def build(tmp_path):
    """Study A: two cines and one still. Study B: one cine. Returns (library, source folder)."""
    src = tmp_path / "in"
    src.mkdir()
    put(src / "secret_name_cine1.dcm", STUDY_A, primary=30.0, secondary=20.0, frames=7)
    put(src / "secret_name_cine2.dcm", STUDY_A, primary=-20.0, secondary=10.0, frames=5)
    put(src / "secret_name_still.dcm", STUDY_A, sop_class=SC_SOP)
    put(src / "other.dcm", STUDY_B, mrn="MRN99999")
    import_path(src, tmp_path / "data" / "store", SALT)
    return Library(tmp_path / "data"), src


def study_uids(lib):
    return {study_of(e.path)[0] for e in lib.entries()}


def test_series_are_grouped_by_study_with_cines_before_stills(tmp_path):
    lib, _ = build(tmp_path)
    groups = series_by_study(lib)
    assert len(groups) == 2
    sizes = sorted(len(v) for v in groups.values())
    assert sizes == [1, 3]
    three = next(v for v in groups.values() if len(v) == 3)
    assert [s.kind for s in three] == ["cine", "cine", "still"]
    assert all(isinstance(s, ExportSeries) for s in three)


def test_series_fields(tmp_path):
    lib, _ = build(tmp_path)
    three = next(v for v in series_by_study(lib).values() if len(v) == 3)
    by_view = {s.view: s for s in three if s.kind == "cine"}
    assert set(by_view) == {"LAO 30 CRAN 20", "RAO 20 CRAN 10"}
    assert by_view["LAO 30 CRAN 20"].frames == 7 and by_view["RAO 20 CRAN 10"].frames == 5
    for s in three:
        assert s.store_file == f"store/{s.series_id}.dcm"
        assert s.study_date == "20261120"
    assert three[-1].kind == "still" and three[-1].frames == 1


def test_keys_are_the_remapped_study_uids(tmp_path):
    lib, _ = build(tmp_path)
    assert set(series_by_study(lib)) == study_uids(lib)
    assert STUDY_A not in series_by_study(lib) and STUDY_B not in series_by_study(lib)


def test_unreadable_stored_files_are_skipped(tmp_path):
    lib, _ = build(tmp_path)
    (lib.store_dir / "9.9.9.dcm").write_bytes(b"junk" * 20)
    assert sum(len(v) for v in series_by_study(lib).values()) == 4


def test_no_original_uid_source_name_or_folder_label_appears(tmp_path):
    lib, src = build(tmp_path)
    lib.assign([e.uid for e in lib.entries()], "Patient John Doe case")      # a label typed by the user
    text = json.dumps({k: [dataclasses.asdict(s) for s in v] for k, v in series_by_study(lib).items()})
    for needle in ("secret_name", "Patient John Doe", STUDY_A, STUDY_B, str(src), "MRN12345", "DOE"):
        assert needle not in text


def test_empty_library_gives_no_groups(tmp_path):
    assert series_by_study(Library(tmp_path / "empty")) == {}
