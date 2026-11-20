from __future__ import annotations

from pathlib import Path

import pydicom

from .models import ImportRejected, XASeries

XA_SOP_CLASSES = {
    "1.2.840.10008.5.1.4.1.1.12.1",    # X-Ray Angiographic Image Storage
    "1.2.840.10008.5.1.4.1.1.12.1.1",  # Enhanced XA Image Storage
}
DEFAULT_FPS = 15.0


def _float_or_none(ds: pydicom.Dataset, keyword: str) -> float | None:
    v = ds.get(keyword)
    return None if v is None or v == "" else float(v)


def read_xa(path: Path) -> XASeries:
    path = Path(path)
    if path.stat().st_size == 0:
        raise ImportRejected(f"{path.name}: file is empty")
    try:
        ds = pydicom.dcmread(path)
    except Exception as exc:  # corrupt or non-DICOM
        raise ImportRejected(f"{path.name}: not a valid DICOM file ({exc})") from exc
    sop = str(ds.get("SOPClassUID", ""))
    if sop not in XA_SOP_CLASSES:
        raise ImportRejected(
            f"{path.name}: not an XA image (SOP class {sop or 'missing'}, "
            f"modality {ds.get('Modality', '?')}); only XA cine series are imported")
    try:
        frames = ds.pixel_array
    except Exception as exc:
        raise ImportRejected(f"{path.name}: cannot decode pixel data ({exc})") from exc
    if frames.ndim == 2:
        frames = frames[None, ...]
    frame_time = _float_or_none(ds, "FrameTime")
    cine_rate = _float_or_none(ds, "CineRate")
    fps = 1000.0 / frame_time if frame_time else (cine_rate or DEFAULT_FPS)
    return XASeries(
        dataset=ds, frames=frames, fps=fps,
        primary_angle=_float_or_none(ds, "PositionerPrimaryAngle"),
        secondary_angle=_float_or_none(ds, "PositionerSecondaryAngle"),
        sop_instance_uid=str(ds.SOPInstanceUID), source=path)
