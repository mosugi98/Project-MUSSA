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


def test_read_header_does_not_decode_pixels(tmp_path):
    from cagsyntax.dicom_import.reader import read_header
    p = make_xa(tmp_path / "c.dcm", primary=-20.0, secondary=10.0)
    ds = pydicom.dcmread(p)
    ds.file_meta.TransferSyntaxUID = JPEGLosslessSV1
    ds.PixelData = encapsulate([bytes(64)] * 5)  # undecodable, header must still read
    ds["PixelData"].is_undefined_length = True
    ds.save_as(p)
    h = read_header(p)
    assert h.view_label == "RAO 20 CRAN 10"
    assert h.series_description == "LAD cine"
    assert h.study_date == "20261120"
    assert h.burned_in_unclear is False  # factory file states BurnedInAnnotation = NO


def test_multiframe_xa_is_a_cine(tmp_path):
    assert read_xa(make_xa(tmp_path / "a.dcm")).kind == "cine"


def test_single_frame_secondary_capture_xa_is_accepted_as_a_still(tmp_path):
    from tests.dicom_factory import SC_SOP
    s = read_xa(make_xa(tmp_path / "s.dcm", sop_class=SC_SOP))
    assert s.kind == "still"
    assert s.frames.shape == (1, 64, 64)
    assert (s.primary_angle, s.secondary_angle) == (30.0, 20.0)


def test_secondary_capture_that_is_not_xa_modality_is_rejected(tmp_path):
    from tests.dicom_factory import SC_SOP
    p = make_xa(tmp_path / "o.dcm", sop_class=SC_SOP)
    ds = pydicom.dcmread(p)
    ds.Modality = "OT"
    ds.save_as(p)
    with pytest.raises(ImportRejected, match="not an XA"):
        read_xa(p)


def test_read_header_reports_kind_and_frame_count(tmp_path):
    from cagsyntax.dicom_import.reader import read_header
    from tests.dicom_factory import SC_SOP
    cine = read_header(make_xa(tmp_path / "a.dcm", frames=7))
    still = read_header(make_xa(tmp_path / "s.dcm", sop_class=SC_SOP))
    assert (cine.kind, cine.frame_count) == ("cine", 7)
    assert (still.kind, still.frame_count) == ("still", 1)


def test_monochrome1_series_are_inverted_to_standard_polarity(tmp_path):
    import numpy as np
    p = make_xa(tmp_path / "m1.dcm")
    raw = read_xa(p).frames.copy()
    ds = pydicom.dcmread(p)
    ds.PhotometricInterpretation = "MONOCHROME1"
    ds.save_as(p)
    inverted = read_xa(p).frames
    assert inverted.dtype == raw.dtype and np.array_equal(inverted, 255 - raw)
    assert read_xa(make_xa(tmp_path / "m2.dcm")).frames.min() == raw.min()      # MONOCHROME2 untouched
