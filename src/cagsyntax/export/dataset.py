from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..dicom_import.models import ImportRejected
from ..dicom_import.reader import read_header
from ..library import Library
from ..scoring import SOURCE, VERSION, Case, score_case
from ..store import CaseStore
from .splits import suggest_split


@dataclass
class ExportSeries:
    series_id: str        # stem of the stored file: the remapped SOP instance uid
    kind: str             # "cine" or "still"
    view: str             # e.g. "RAO 27 CRAN 18"
    frames: int
    study_date: str
    store_file: str       # "store/<series_id>.dcm", relative to the app's data folder


@dataclass
class ExportCase:
    case_id: str                  # remapped study uid
    patient_key: str              # salted MRN hash: keeps all cases of one patient together
    suggested_split: str          # "train" | "val" | "test", from the patient key
    confirmed_at: str
    confirmed_by_level: str       # the level only, never the scorer's name
    reference: dict               # the confirmed snapshot and its breakdown
    rescored: dict                # the current engine on the same form: total, group, consistent
    series: list[ExportSeries] = field(default_factory=list)


@dataclass
class Exclusion:
    case_id: str
    reason: str


@dataclass
class ExportDataset:
    created: str
    engine_source: str
    engine_version: str
    include_stills: bool
    cases: list[ExportCase] = field(default_factory=list)
    excluded: list[Exclusion] = field(default_factory=list)


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


def _reference(confirmation, case: Case, result) -> dict:
    complete = result.status == "complete"
    lesions = []
    for i, les in enumerate(case.lesions):
        lr = result.lesions[i] if complete else None
        lesions.append({
            "segments": list(les.segments),
            "total": lr.total if lr else None,
            "parts": [{"label": p.label, "points": p.points} for p in lr.parts] if lr else [],
        })
    return {
        "total": confirmation.total, "group": confirmation.group,
        "dominance": case.dominance,
        "scoring_dominance": case.scoring_dominance or (case.dominance if case.dominance in ("right", "left") else None),
        "lesions": lesions, "diffuse_segments": list(case.diffuse_segments), "form": confirmation.form,
    }


def build_dataset(store: CaseStore, library: Library, include_stills: bool = False) -> ExportDataset:
    """Every confirmed case with its reference, a re-score by the current engine and its series.
    Cases that cannot be exported are listed in `excluded` with a reason."""
    dataset = ExportDataset(created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            engine_source=SOURCE, engine_version=VERSION, include_stills=include_stills)
    groups = series_by_study(library)
    for confirmed in store.confirmed_cases():
        uid, conf = confirmed.study_uid, confirmed.confirmation
        series = groups.get(uid, [])
        if not series:
            dataset.excluded.append(Exclusion(uid, "no series left in the app for this case"))
            continue
        chosen = [s for s in series if include_stills or s.kind == "cine"]
        if not chosen:
            dataset.excluded.append(Exclusion(uid, "only still images; stills are excluded unless requested"))
            continue
        try:
            case = Case.from_dict(conf.form)
        except (KeyError, TypeError, ValueError):
            dataset.excluded.append(Exclusion(uid, "the confirmed form could not be read"))
            continue
        result = score_case(case)
        rescored = {"total": result.total, "group": result.group,
                    "consistent": result.status == "complete" and result.total == conf.total
                    and result.group == conf.group}
        dataset.cases.append(ExportCase(
            case_id=uid, patient_key=confirmed.mrn_hash, suggested_split=suggest_split(confirmed.mrn_hash),
            confirmed_at=conf.confirmed_at, confirmed_by_level=conf.confirmed_by.level,
            reference=_reference(conf, case, result), rescored=rescored, series=chosen))
    return dataset
