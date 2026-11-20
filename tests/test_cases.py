import pydicom

from cagsyntax.cases import StudyInfo, studies_in_store, study_of
from cagsyntax.dicom_import.deidentify import hash_mrn
from cagsyntax.dicom_import.importer import import_path
from cagsyntax.dicom_import.reader import read_header
from cagsyntax.library import Library
from tests.dicom_factory import SC_SOP, make_xa

SALT = b"s" * 32


def set_study(path, uid):
    ds = pydicom.dcmread(path)
    ds.StudyInstanceUID = uid
    ds.save_as(path)
    return path


def build(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    set_study(make_xa(src / "a1.dcm"), "1.2.3.1")
    set_study(make_xa(src / "a2.dcm", primary=-20.0), "1.2.3.1")
    set_study(make_xa(src / "a3.dcm", sop_class=SC_SOP), "1.2.3.1")
    set_study(make_xa(src / "b1.dcm", mrn="MRN99999"), "1.2.3.2")
    import_path(src, tmp_path / "data" / "store", SALT)
    return Library(tmp_path / "data")


def test_header_has_remapped_study_uid_and_mrn_hash(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    original = pydicom.dcmread(set_study(make_xa(src / "a.dcm"), "1.2.3.1")).StudyInstanceUID
    item = import_path(src, tmp_path / "store", SALT).imported[0]
    h = read_header(item.stored_path)
    assert h.study_uid and h.study_uid != original
    assert len(h.mrn_hash) == 64 and h.mrn_hash == hash_mrn("MRN12345", SALT)


def test_series_of_one_study_are_grouped(tmp_path):
    lib = build(tmp_path)
    studies = studies_in_store(lib)
    assert len(studies) == 2
    counts = sorted((s.series_count, s.cine_count) for s in studies.values())
    assert counts == [(1, 1), (3, 2)]          # study 1: two cines + one still; study 2: one cine
    assert all(isinstance(s, StudyInfo) and len(s.mrn_hash) == 64 for s in studies.values())


def test_study_of_returns_uid_and_hash_for_one_stored_file(tmp_path):
    lib = build(tmp_path)
    entry = lib.entries()[0]
    uid, mrn_hash = study_of(entry.path)
    assert uid in studies_in_store(lib) and len(mrn_hash) == 64


def test_unreadable_stored_file_is_skipped(tmp_path):
    lib = build(tmp_path)
    (lib.store_dir / "9.9.9.dcm").write_bytes(b"not dicom" * 10)
    assert len(studies_in_store(lib)) == 2
