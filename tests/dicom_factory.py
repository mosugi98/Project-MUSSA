"""Synthetic XA DICOM builder for tests. Never contains real patient data."""
from pathlib import Path

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

XA_SOP = "1.2.840.10008.5.1.4.1.1.12.1"
DOSE_SR_SOP = "1.2.840.10008.5.1.4.1.1.88.67"
SC_SOP = "1.2.840.10008.5.1.4.1.1.7"  # Secondary Capture (operator-saved key frame)


def make_xa(path: Path, *, frames: int = 5, rows: int = 64, cols: int = 64,
            primary: float | None = 30.0, secondary: float | None = 20.0,
            mrn: str = "MRN12345", name: str = "DOE^JOHN",
            sop_class: str = XA_SOP, burned_in: bool = False,
            frame_time_ms: float | None = 66.7) -> Path:
    path = Path(path)
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop_class
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "XA" if sop_class in (XA_SOP, SC_SOP) else "SR"
    ds.PatientName = name
    ds.PatientID = mrn
    ds.PatientBirthDate = "19600101"
    ds.AccessionNumber = "ACC987"
    ds.ReferringPhysicianName = "REF^DOCTOR"
    ds.InstitutionName = "Some Hospital"
    ds.StudyDate = "20261120"
    ds.SeriesDescription = "LAD cine"
    ds.BurnedInAnnotation = "YES" if burned_in else "NO"
    if primary is not None:
        ds.PositionerPrimaryAngle = primary
    if secondary is not None:
        ds.PositionerSecondaryAngle = secondary
    if frame_time_ms is not None:
        ds.FrameTime = frame_time_ms
    if sop_class in (XA_SOP, SC_SOP):
        if sop_class == SC_SOP:
            frames = 1
        rng = np.random.default_rng(0)
        px = rng.integers(0, 256, size=(frames, rows, cols), dtype=np.uint8)
        if sop_class == XA_SOP:
            ds.NumberOfFrames = frames
        ds.Rows, ds.Columns = rows, cols
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = ds.BitsStored = 8
        ds.HighBit = 7
        ds.PixelRepresentation = 0
        ds.PixelData = px.tobytes()
    ds.save_as(path, implicit_vr=False, little_endian=True)
    return path
