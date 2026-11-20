from __future__ import annotations

import hashlib
from pathlib import Path

import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import PYDICOM_IMPLEMENTATION_UID

# The only header elements an exported image keeps: the identifiers already remapped on import,
# the study date (the project spec keeps it), the image geometry and pixel data, the cine timing and
# the C-arm angles. Everything else in the stored file (series and study descriptions, protocol and
# physician names, patient sex and age, times, private tags, ...) is dropped.
KEEP = (
    "SOPClassUID", "SOPInstanceUID", "StudyInstanceUID", "SeriesInstanceUID", "FrameOfReferenceUID",
    "Modality", "StudyDate", "PatientID", "PatientIdentityRemoved", "ImageType", "ConversionType",
    "BurnedInAnnotation", "LossyImageCompression", "LossyImageCompressionMethod",
    "LossyImageCompressionRatio",
    "SamplesPerPixel", "PhotometricInterpretation", "PlanarConfiguration", "Rows", "Columns",
    "BitsAllocated", "BitsStored", "HighBit", "PixelRepresentation", "NumberOfFrames",
    "FrameIncrementPointer", "PixelSpacing", "ImagerPixelSpacing", "PixelIntensityRelationship",
    "PixelIntensityRelationshipSign", "WindowCenter", "WindowWidth", "RescaleIntercept", "RescaleSlope",
    "RescaleType", "PresentationLUTShape",
    "FrameTime", "CineRate", "RecommendedDisplayFrameRate", "StartTrim", "StopTrim",
    "PositionerPrimaryAngle", "PositionerSecondaryAngle", "PositionerMotion",
    "DistanceSourceToDetector", "DistanceSourceToPatient", "EstimatedRadiographicMagnificationFactor",
    "PixelData",
)


def write_clean_copy(source: Path, target: Path) -> str:
    """Write a copy of a stored image that keeps only the KEEP elements. Returns the SHA-256 of the
    written file (hashed in chunks)."""
    ds = pydicom.dcmread(source)
    clean = Dataset()
    for keyword in KEEP:
        if keyword in ds:
            clean[keyword] = ds[keyword]
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = ds.file_meta.MediaStorageSOPClassUID
    meta.MediaStorageSOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    meta.TransferSyntaxUID = ds.file_meta.TransferSyntaxUID
    meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    clean.file_meta = meta
    clean.save_as(target, enforce_file_format=True)
    digest = hashlib.sha256()
    with open(target, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
