import pydicom
from tests.dicom_factory import make_xa


def test_make_xa_roundtrip(tmp_path):
    p = make_xa(tmp_path / "a.dcm")
    ds = pydicom.dcmread(p)
    assert ds.NumberOfFrames == 5
    assert ds.pixel_array.shape == (5, 64, 64)
    assert ds.PositionerPrimaryAngle == 30.0
    assert ds.PatientID == "MRN12345"
