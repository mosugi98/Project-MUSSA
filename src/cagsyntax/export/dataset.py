from __future__ import annotations

from dataclasses import dataclass

from ..dicom_import.models import ImportRejected
from ..dicom_import.reader import read_header
from ..library import Library


@dataclass
class ExportSeries:
    series_id: str        # stem of the stored file: the remapped SOP instance uid
    kind: str             # "cine" or "still"
    view: str             # e.g. "RAO 27 CRAN 18"
    frames: int
    study_date: str
    store_file: str       # "store/<series_id>.dcm", relative to the app's data folder


def series_by_study(library: Library) -> dict[str, list[ExportSeries]]:
    """Stored series grouped by (remapped) study uid; cines before stills, then by series id.
    Unreadable stored files are skipped. Nothing from the original files is exposed: no source
    names, no original UIDs, no folder labels."""
    groups: dict[str, list[ExportSeries]] = {}
    for entry in library.entries():
        try:
            h = read_header(entry.path)
        except ImportRejected:
            continue
        if not h.study_uid:
            continue
        groups.setdefault(h.study_uid, []).append(ExportSeries(
            series_id=entry.uid, kind=h.kind, view=h.view_label, frames=h.frame_count,
            study_date=h.study_date, store_file=f"store/{entry.uid}.dcm"))
    for series in groups.values():
        series.sort(key=lambda s: (s.kind != "cine", s.series_id))
    return groups
