import pydicom
import pytest

from pydicom.dataset import Dataset

from cagsyntax.dicom_import.deidentify import (
    deidentify, get_or_create_salt, hash_mrn, identifier_strings, scan_identifiers)
from tests.dicom_factory import make_xa

FORBIDDEN = ["DOE", "JOHN", "MRN12345"]
SALT = b"s" * 32


@pytest.fixture
def ds(tmp_path):
    d = pydicom.dcmread(make_xa(tmp_path / "a.dcm"))
    d.OperatorsName = "OPER^ATOR"
    d.PatientAddress = "1 Some Street"
    d.OtherPatientIDs = "OTHER1"
    d.StudyID = "STUDY1"
    d.add_new(0x00110010, "LO", "PRIVATE CREATOR")
    d.add_new(0x00111001, "LO", "DOE private copy")
    return d


def blank(ds, kw):
    return not str(ds.get(kw, ""))


def test_scan_detects_leak_in_original(ds):
    assert scan_identifiers(ds, FORBIDDEN)


def test_strips_direct_identifiers(ds):
    out, _, _ = deidentify(ds, SALT)
    for kw in ["PatientName", "PatientBirthDate", "PatientAddress",
               "OtherPatientIDs", "AccessionNumber", "ReferringPhysicianName",
               "OperatorsName", "InstitutionName", "StudyID"]:
        assert blank(out, kw), kw


def test_keeps_study_date_modality_series_description_angles(ds):
    out, _, _ = deidentify(ds, SALT)
    assert out.StudyDate == "20261120"
    assert out.Modality == "XA"
    assert out.SeriesDescription == "LAD cine"
    assert out.PositionerPrimaryAngle == 30.0
    assert out.PositionerSecondaryAngle == 20.0


def test_removes_private_tags(ds):
    out, _, _ = deidentify(ds, SALT)
    assert not any(e.tag.is_private for e in out)


def test_scan_finds_no_identifiers_after_deidentify(ds):
    out, _, _ = deidentify(ds, SALT)
    assert scan_identifiers(out, FORBIDDEN) == []


def test_original_dataset_is_not_modified(ds):
    deidentify(ds, SALT)
    assert ds.PatientID == "MRN12345"


def test_hash_is_stable_and_salted():
    h = hash_mrn("MRN12345", SALT)
    assert h == hash_mrn("MRN12345", SALT)
    assert h != hash_mrn("MRN12345", b"t" * 32)
    assert h == hash_mrn("mrn12345 ", SALT)
    assert "MRN12345" not in h.upper()


def test_deidentify_returns_hash_of_original_mrn(ds):
    _, h, _ = deidentify(ds, SALT)
    assert h == hash_mrn("MRN12345", SALT)


def test_salt_persisted(tmp_path):
    a = get_or_create_salt(tmp_path)
    assert len(a) == 32
    assert get_or_create_salt(tmp_path) == a


def test_burned_in_annotation_warns(tmp_path):
    d = pydicom.dcmread(make_xa(tmp_path / "b.dcm", burned_in=True))
    _, _, warnings = deidentify(d, SALT)
    assert any("burned-in" in w for w in warnings)


def test_no_warning_when_not_burned_in(ds):
    _, _, warnings = deidentify(ds, SALT)
    assert not any("burned-in" in w for w in warnings)


def nested(ds):
    ra = Dataset()
    ra.AccessionNumber = "ACC987"
    ra.RequestedProcedureID = "PROC55"
    ds.RequestAttributesSequence = [ra]
    other = Dataset()
    other.PatientID = "OTHERMRN77"
    other.IssuerOfPatientID = "HOSP1"
    ds.OtherPatientIDsSequence = [other]
    ds.RequestingPhysician = "SMITH^ALICE"
    ds.ImageComments = "Pt John Doe"
    return ds


def test_strips_identifiers_in_nested_sequences_and_secondary_fields(ds):
    out, _, _ = deidentify(nested(ds), SALT)
    leaks = scan_identifiers(out, ["ACC987", "PROC55", "OTHERMRN77", "HOSP1", "SMITH", "ALICE", "John Doe"])
    assert leaks == []


def test_identifier_strings_collects_from_removed_fields_including_nested(ds):
    strings = identifier_strings(nested(ds))
    for expected in ["DOE", "JOHN", "MRN12345", "ACC987", "OTHERMRN77", "SMITH", "ALICE"]:
        assert expected in strings, expected


def test_scan_uses_word_boundaries_and_skips_numeric_vrs(ds):
    ds.ManufacturerModelName = "AXIOM-Artis"
    ds.StudyTime = "101530.000"
    assert scan_identifiers(ds, ["ARTI", "101530"]) == []
    assert scan_identifiers(ds, ["ARTIS"]) != []


def test_patient_id_is_replaced_by_the_mrn_hash(ds):
    out, h, _ = deidentify(ds, SALT)
    assert out.PatientID == h == hash_mrn("MRN12345", SALT)


def test_uids_are_remapped_deterministically(ds):
    a, _, _ = deidentify(ds, SALT)
    b, _, _ = deidentify(ds, SALT)
    c, _, _ = deidentify(ds, b"t" * 32)
    assert a.SOPInstanceUID != ds.SOPInstanceUID
    assert a.SOPInstanceUID == b.SOPInstanceUID != c.SOPInstanceUID
    assert a.SOPInstanceUID.startswith("2.25.")
    assert a.StudyInstanceUID != ds.StudyInstanceUID
    assert a.file_meta.MediaStorageSOPInstanceUID == a.SOPInstanceUID
    assert a.SOPClassUID == ds.SOPClassUID


def test_file_meta_identifiers_removed(ds):
    ds.file_meta.SourceApplicationEntityTitle = "CATHLAB1"
    out, _, _ = deidentify(ds, SALT)
    assert "SourceApplicationEntityTitle" not in out.file_meta


def test_burned_in_absent_also_warns(ds):
    del ds.BurnedInAnnotation
    _, _, warnings = deidentify(ds, SALT)
    assert any("burned-in" in w for w in warnings)
