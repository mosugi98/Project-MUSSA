import pydicom
import pytest
from pydicom.dataset import Dataset

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


def edit(path, fn):
    ds = pydicom.dcmread(path)
    fn(ds)
    ds.save_as(path)
    return path


def test_stored_uid_is_remapped_and_names_the_file(tmp_path):
    (tmp_path / "in").mkdir()
    src = make_xa(tmp_path / "in" / "a.dcm")
    original = pydicom.dcmread(src).SOPInstanceUID
    item = import_path(src, tmp_path / "store", SALT).imported[0]
    assert item.sop_instance_uid != original
    assert item.stored_path.stem == item.sop_instance_uid
    assert pydicom.dcmread(item.stored_path).SOPInstanceUID == item.sop_instance_uid


def test_stored_patient_id_is_the_hash(tmp_path):
    (tmp_path / "in").mkdir()
    item = import_path(make_xa(tmp_path / "in" / "a.dcm"), tmp_path / "store", SALT).imported[0]
    assert pydicom.dcmread(item.stored_path).PatientID == item.mrn_hash


def test_path_traversal_uid_stays_inside_store(tmp_path):
    (tmp_path / "in").mkdir()
    src = edit(make_xa(tmp_path / "in" / "a.dcm"), lambda d: setattr(d, "SOPInstanceUID", "../escaped"))
    r = import_path(src, tmp_path / "store", SALT)
    assert not (tmp_path / "escaped.dcm").exists()
    assert all(i.stored_path.parent == tmp_path / "store" for i in r.imported)


def test_missing_sop_uid_is_rejected_and_folder_continues(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    make_xa(d / "good.dcm")
    edit(make_xa(d / "bad.dcm"), lambda ds: ds.__delattr__("SOPInstanceUID"))
    r = import_path(d, tmp_path / "store", SALT)
    assert len(r.imported) == 1 and len(r.rejected) == 1


def test_multivalued_angle_imports_as_unknown_view(tmp_path):
    (tmp_path / "in").mkdir()
    src = edit(make_xa(tmp_path / "in" / "a.dcm"), lambda ds: setattr(ds, "PositionerPrimaryAngle", [30.0, 40.0]))
    r = import_path(src, tmp_path / "store", SALT)
    assert r.imported[0].view_label == "Unknown view"


def test_save_failure_is_rejected_leaves_no_partial_file_and_retry_works(tmp_path, monkeypatch):
    (tmp_path / "in").mkdir()
    src = make_xa(tmp_path / "in" / "a.dcm")
    store = tmp_path / "store"
    real = Dataset.save_as

    def boom(self, *a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(Dataset, "save_as", boom)
    r = import_path(src, store, SALT)
    assert len(r.rejected) == 1 and r.imported == []
    assert list(store.glob("*")) == []
    monkeypatch.setattr(Dataset, "save_as", real)
    r2 = import_path(src, store, SALT)
    assert len(r2.imported) == 1


def test_nested_identifiers_are_stripped_and_import_succeeds(tmp_path):
    (tmp_path / "in").mkdir()

    def add(ds):
        ra = Dataset()
        ra.AccessionNumber = "ACC987"
        ds.RequestAttributesSequence = [ra]

    src = edit(make_xa(tmp_path / "in" / "a.dcm"), add)
    r = import_path(src, tmp_path / "store", SALT)
    assert len(r.imported) == 1
    assert scan_identifiers(pydicom.dcmread(r.imported[0].stored_path), ["ACC987"]) == []


def test_numeric_mrn_does_not_false_positive_on_time(tmp_path):
    (tmp_path / "in").mkdir()
    src = edit(make_xa(tmp_path / "in" / "a.dcm", mrn="101530"), lambda ds: setattr(ds, "StudyTime", "101530.000"))
    assert len(import_path(src, tmp_path / "store", SALT).imported) == 1


def test_short_name_that_is_a_prefix_of_a_device_name_does_not_false_positive(tmp_path):
    (tmp_path / "in").mkdir()
    src = edit(make_xa(tmp_path / "in" / "a.dcm", name="ARTI"), lambda ds: setattr(ds, "ManufacturerModelName", "AXIOM-Artis"))
    assert len(import_path(src, tmp_path / "store", SALT).imported) == 1


def test_failed_deid_check_names_the_leaking_tag_and_stores_nothing(tmp_path):
    (tmp_path / "in").mkdir()
    src = edit(make_xa(tmp_path / "in" / "a.dcm"), lambda ds: setattr(ds, "SeriesDescription", "scan of DOE"))
    store = tmp_path / "store"
    r = import_path(src, store, SALT)
    assert r.imported == [] and "SeriesDescription" in r.rejected[0][1]
    assert not store.exists() or list(store.glob("*")) == []
