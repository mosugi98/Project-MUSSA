from __future__ import annotations

import re
from pathlib import Path

from .deidentify import deidentify, scan_identifiers
from .models import ImportedItem, ImportRejected, ImportResult
from .reader import read_xa
from .views import label_view


def _identifier_strings(ds) -> list[str]:
    """Strings that must not survive in stored output: name parts and the MRN.
    Tokens shorter than 3 characters are skipped to avoid false positives."""
    tokens = re.split(r"[\^\s]+", str(ds.get("PatientName", "")))
    tokens.append(str(ds.get("PatientID", "")).strip())
    return [t for t in tokens if len(t) >= 3]


def _import_one(path: Path, store_dir: Path, salt: bytes, result: ImportResult) -> None:
    series = read_xa(path)
    dest = store_dir / f"{series.sop_instance_uid}.dcm"
    if dest.exists():
        result.skipped_duplicates.append(path)
        return
    out, mrn_hash, warnings = deidentify(series.dataset, salt)
    if scan_identifiers(out, _identifier_strings(series.dataset)):
        raise ImportRejected(f"{path.name}: de-identification check failed; nothing was stored")
    store_dir.mkdir(parents=True, exist_ok=True)
    out.save_as(dest)
    result.imported.append(ImportedItem(
        stored_path=dest, sop_instance_uid=series.sop_instance_uid, mrn_hash=mrn_hash,
        view_label=label_view(series.primary_angle, series.secondary_angle),
        study_date=str(out.get("StudyDate", "")),
        series_description=str(out.get("SeriesDescription", "")),
        warnings=warnings))


def import_path(src: Path, store_dir: Path, salt: bytes) -> ImportResult:
    src, store_dir = Path(src), Path(store_dir)
    files = sorted(p for p in src.rglob("*") if p.is_file()) if src.is_dir() else [src]
    result = ImportResult()
    for path in files:
        try:
            _import_one(path, store_dir, salt, result)
        except ImportRejected as exc:
            result.rejected.append((path, str(exc)))
    return result
