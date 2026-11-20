from __future__ import annotations

from pathlib import Path

import pydicom

from .models import ImportRejected, SeriesHeader, XASeries
from .views import label_view

XA_SOP_CLASSES = {
    "1.2.840.10008.5.1.4.1.1.12.1",    # X-Ray Angiographic Image Storage
    "1.2.840.10008.5.1.4.1.1.12.1.1",  # Enhanced XA Image Storage
}
# Operator-saved key frames: single-frame Secondary Capture images whose modality is XA.
# They are accepted as secondary reference "stills"; cine series are the primary data.
SECONDARY_CAPTURE_SOP = "1.2.840.10008.5.1.4.1.1.7"
DEFAULT_FPS = 15.0


def _frame_count(ds: pydicom.Dataset) -> int:
    try:
        return max(1, int(ds.get("NumberOfFrames", 1)))
    except (TypeError, ValueError):
        return 1


def _float_or_none(ds: pydicom.Dataset, keyword: str) -> float | None:
    v = ds.get(keyword)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):  # e.g. multi-valued or malformed
        return None


def read_xa(path: Path) -> XASeries:
    path = Path(path)
    if path.stat().st_size == 0:
        raise ImportRejected(f"{path.name}: file is empty")
    try:
        ds = pydicom.dcmread(path)
    except Exception as exc:  # corrupt or non-DICOM
        raise ImportRejected(f"{path.name}: not a valid DICOM file ({exc})") from exc
    if not ds.get("SOPInstanceUID"):
        raise ImportRejected(f"{path.name}: missing SOPInstanceUID")
    sop = str(ds.get("SOPClassUID", ""))
    is_xa_still = sop == SECONDARY_CAPTURE_SOP and str(ds.get("Modality", "")) == "XA"
    if sop not in XA_SOP_CLASSES and not is_xa_still:
        raise ImportRejected(
            f"{path.name}: not an XA image (SOP class {sop or 'missing'}, "
            f"modality {ds.get('Modality', '?')}); only XA cine series and XA key-frame "
            f"stills are imported")
    if int(ds.get("SamplesPerPixel", 1)) != 1:
        raise ImportRejected(f"{path.name}: not a grayscale image; cannot import")
    try:
        frames = ds.pixel_array
    except Exception as exc:
        raise ImportRejected(f"{path.name}: cannot decode pixel data ({exc})") from exc
    if frames.ndim == 2:
        frames = frames[None, ...]
    frame_time = _float_or_none(ds, "FrameTime")
    cine_rate = _float_or_none(ds, "CineRate")
    fps = 1000.0 / frame_time if frame_time and frame_time > 0 else (cine_rate if cine_rate and cine_rate > 0 else DEFAULT_FPS)
    return XASeries(
        dataset=ds, frames=frames, fps=fps,
        primary_angle=_float_or_none(ds, "PositionerPrimaryAngle"),
        secondary_angle=_float_or_none(ds, "PositionerSecondaryAngle"),
        sop_instance_uid=str(ds.SOPInstanceUID), source=path,
        kind="cine" if frames.shape[0] > 1 else "still")


def read_header(path: Path) -> SeriesHeader:
    """Fast: reads tags only, never decodes pixel data."""
    path = Path(path)
    try:
        ds = pydicom.dcmread(path, stop_before_pixels=True)
    except Exception as exc:
        raise ImportRejected(f"{path.name}: not a valid DICOM file ({exc})") from exc
    return SeriesHeader(
        view_label=label_view(_float_or_none(ds, "PositionerPrimaryAngle"),
                              _float_or_none(ds, "PositionerSecondaryAngle")),
        series_description=str(ds.get("SeriesDescription", "")),
        study_date=str(ds.get("StudyDate", "")),
        burned_in_unclear=str(ds.get("BurnedInAnnotation", "")).upper() != "NO",
        kind="cine" if _frame_count(ds) > 1 else "still", frame_count=_frame_count(ds))
