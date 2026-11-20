import pydicom
import pytest
from pydicom.encaps import encapsulate
from pydicom.uid import JPEGLosslessSV1

from cagsyntax.dicom_import.models import ImportRejected
from cagsyntax.dicom_import.reader import read_xa
from tests.dicom_factory import DOSE_SR_SOP, make_xa


def test_reads_valid_xa(tmp_path):
    s = read_xa(make_xa(tmp_path / "a.dcm"))
    assert s.frames.shape == (5, 64, 64)
    assert s.fps == pytest.approx(1000 / 66.7)
    assert (s.primary_angle, s.secondary_angle) == (30.0, 20.0)


def test_missing_frame_time_defaults_to_15_fps(tmp_path):
    s = read_xa(make_xa(tmp_path / "a.dcm", frame_time_ms=None))
    assert s.fps == 15.0


def test_rejects_dose_sr(tmp_path):
    with pytest.raises(ImportRejected, match="not an XA"):
        read_xa(make_xa(tmp_path / "sr.dcm", sop_class=DOSE_SR_SOP))


def test_rejects_corrupt_file(tmp_path):
    p = tmp_path / "bad.dcm"
    p.write_bytes(bytes(range(256)) * 4)
    with pytest.raises(ImportRejected, match="not a valid DICOM"):
        read_xa(p)


def test_rejects_zero_byte_file(tmp_path):
    p = tmp_path / "empty.dcm"
    p.write_bytes(b"")
    with pytest.raises(ImportRejected, match="empty"):
        read_xa(p)


def test_rejects_compressed_without_decoder(tmp_path):
    p = make_xa(tmp_path / "c.dcm")
    ds = pydicom.dcmread(p)
    ds.file_meta.TransferSyntaxUID = JPEGLosslessSV1
    ds.PixelData = encapsulate([bytes(64)] * 5)
    ds["PixelData"].is_undefined_length = True
    ds.save_as(p)
    with pytest.raises(ImportRejected, match="cannot decode"):
        read_xa(p)
