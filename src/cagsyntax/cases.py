from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .dicom_import.models import ImportRejected
from .dicom_import.reader import read_header
from .library import Library


@dataclass
class StudyInfo:
    study_uid: str
    mrn_hash: str
    series_count: int
    cine_count: int


def study_of(path: Path) -> tuple[str, str]:
    """(study uid, MRN hash) of one stored series."""
    h = read_header(path)
    return h.study_uid, h.mrn_hash


def studies_in_store(library: Library) -> dict[str, StudyInfo]:
    """Group the stored series into studies (a study is a case). Unreadable files are skipped."""
    studies: dict[str, StudyInfo] = {}
    for entry in library.entries():
        try:
            h = read_header(entry.path)
        except ImportRejected:
            continue
        if not h.study_uid:
            continue
        info = studies.setdefault(h.study_uid, StudyInfo(h.study_uid, h.mrn_hash, 0, 0))
        info.series_count += 1
        info.cine_count += 1 if h.kind == "cine" else 0
    return studies
