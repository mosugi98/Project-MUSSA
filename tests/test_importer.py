import pydicom

from cagsyntax.dicom_import.deidentify import hash_mrn, scan_identifiers
from cagsyntax.dicom_import.importer import import_path
from tests.dicom_factory import DOSE_SR_SOP, make_xa

SALT = b"s" * 32


def test_imports_single_file(tmp_path):
    (tmp_path / "in").mkdir()
    src = make_xa(tmp_path / "in" / "a.dcm")
    store = tmp_path / "store"
    r = import_path(src, store, SALT)
    assert len(r.imported) == 1 and not r.rejected and not r.skipped_duplicates
    item = r.imported[0]
    assert item.stored_path.exists()
    assert item.view_label == "LAO 30 CRAN 20"
    assert item.mrn_hash == hash_mrn("MRN12345", SALT)
    assert item.study_date == "20261120"
    assert item.series_description == "LAD cine"
    assert str(pydicom.dcmread(item.stored_path).PatientName) == ""


def test_stored_output_has_no_identifiers(tmp_path):
    (tmp_path / "in").mkdir()
    r = import_path(make_xa(tmp_path / "in" / "a.dcm"), tmp_path / "store", SALT)
    stored = pydicom.dcmread(r.imported[0].stored_path)
    assert scan_identifiers(stored, ["DOE", "JOHN", "MRN12345"]) == []


def test_duplicate_import_is_skipped(tmp_path):
    (tmp_path / "in").mkdir()
    src = make_xa(tmp_path / "in" / "a.dcm")
    import_path(src, tmp_path / "store", SALT)
    r = import_path(src, tmp_path / "store", SALT)
    assert r.skipped_duplicates == [src] and r.imported == []
    assert len(list((tmp_path / "store").glob("*.dcm"))) == 1


def test_mixed_folder(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    make_xa(d / "a.dcm")
    make_xa(d / "b.dcm", primary=-30.0, secondary=-10.0)
    (d / "zero.dcm").write_bytes(b"")
    (d / "notes.txt").write_text("hello")
    make_xa(d / "sr.dcm", sop_class=DOSE_SR_SOP)
    r = import_path(d, tmp_path / "store", SALT)
    assert len(r.imported) == 2
    assert len(r.rejected) == 3
    assert all(msg for _, msg in r.rejected)
    assert {p.name for p, _ in r.rejected} == {"zero.dcm", "notes.txt", "sr.dcm"}


def test_same_mrn_same_hash_across_files(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    make_xa(d / "a.dcm")
    make_xa(d / "b.dcm", primary=-20.0)
    r = import_path(d, tmp_path / "store", SALT)
    assert len({i.mrn_hash for i in r.imported}) == 1


def test_burned_in_warning_reaches_import_result(tmp_path):
    (tmp_path / "in").mkdir()
    r = import_path(make_xa(tmp_path / "in" / "a.dcm", burned_in=True), tmp_path / "store", SALT)
    assert any("burned-in" in w for w in r.imported[0].warnings)
