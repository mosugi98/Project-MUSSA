from __future__ import annotations

import os
from pathlib import Path

from .deidentify import deidentify, identifier_strings, scan_identifiers
from .models import ImportedItem, ImportRejected, ImportResult
from .reader import read_xa
from .views import label_view


def _import_one(path: Path, store_dir: Path, salt: bytes, result: ImportResult) -> None:
    series = read_xa(path)
    out, mrn_hash, warnings = deidentify(series.dataset, salt)
    uid = str(out.SOPInstanceUID)  # remapped, so safe to use as a file name
    dest = store_dir / f"{uid}.dcm"
    if dest.exists():
        result.skipped_duplicates.append(path)
        return
    leaks = scan_identifiers(out, identifier_strings(series.dataset))
    if leaks:
        fields = ", ".join(sorted({leak.split(" ", 1)[0] for leak in leaks}))
        raise ImportRejected(f"{path.name}: de-identification check failed (still found in: "
                             f"{fields}); nothing was stored")
    store_dir.mkdir(parents=True, exist_ok=True)
    tmp = store_dir / f".{uid}.tmp"
    try:
        out.save_as(tmp)
        os.replace(tmp, dest)  # atomic: a half-written file never looks like an import
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    result.imported.append(ImportedItem(
        stored_path=dest, sop_instance_uid=uid, mrn_hash=mrn_hash,
        view_label=label_view(series.primary_angle, series.secondary_angle),
        study_date=str(out.get("StudyDate", "")),
        series_description=str(out.get("SeriesDescription", "")),
        warnings=warnings, kind=series.kind))


def import_path(src: Path, store_dir: Path, salt: bytes) -> ImportResult:
    src, store_dir = Path(src), Path(store_dir)
    files = sorted(p for p in src.rglob("*") if p.is_file()) if src.is_dir() else [src]
    result = ImportResult()
    for path in files:
        try:
            _import_one(path, store_dir, salt, result)
        except ImportRejected as exc:
            result.rejected.append((path, str(exc)))
        except Exception as exc:  # one bad file must never abort the folder
            result.rejected.append((path, f"{path.name}: unexpected error ({exc})"))
    return result
