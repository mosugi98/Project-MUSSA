from __future__ import annotations

import csv
import json
import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..library import Library
from .dataset import ExportCase, ExportDataset
from .images import write_clean_copy

FORMAT_VERSION = 1
NOTICE = ("De-identified research data exported from MUSSA. Educational tool, not a certified medical "
          "device. Not for clinical decisions.")
CASE_COLUMNS = ["case_id", "patient_key", "suggested_split", "reference_total", "reference_group",
                "dominance", "scoring_dominance", "n_lesions", "n_series", "n_cines",
                "consistent_with_engine"]
SERIES_COLUMNS = ["case_id", "series_id", "kind", "view", "frames", "burned_in_unclear", "path"]
TEMP_MARKER = ".mussa-export-tmp"   # lets us recognise (and only ever remove) our own leftovers


class ExportCancelled(Exception):
    """The user cancelled the export; nothing was written."""


@dataclass
class ExportResult:
    folder: Path
    cases: int
    series: int
    excluded: int
    inconsistent: int
    images_copied: int
    burned_in_unclear: int = 0


def _series_path(series, copy_images: bool) -> str:
    return f"images/{series.series_id}.dcm" if copy_images else series.store_file


def _payload(dataset: ExportDataset, copy_images: bool, hashes: dict[str, str]) -> dict:
    cases = []
    for c in dataset.cases:
        series = []
        for s in c.series:
            item = {"series_id": s.series_id, "kind": s.kind, "view": s.view, "frames": s.frames,
                    "study_date": s.study_date, "burned_in_unclear": s.burned_in_unclear,
                    "path": _series_path(s, copy_images)}
            if copy_images:
                item["sha256"] = hashes[s.series_id]
            series.append(item)
        cases.append({"case_id": c.case_id, "patient_key": c.patient_key,
                      "suggested_split": c.suggested_split, "confirmed_at": c.confirmed_at,
                      "confirmed_by_level": c.confirmed_by_level, "reference": c.reference,
                      "rescored": c.rescored, "series": series})
    inconsistent = sum(1 for c in dataset.cases if not c.rescored["consistent"])
    n_series = sum(len(c.series) for c in dataset.cases)
    burned_in = sum(1 for c in dataset.cases for s in c.series if s.burned_in_unclear)
    no_key = sum(1 for c in dataset.cases if c.patient_key is None)
    return {
        "format_version": FORMAT_VERSION, "created": dataset.created,
        "engine": {"source": dataset.engine_source, "version": dataset.engine_version},
        "options": {"include_stills": dataset.include_stills, "images_copied": copy_images},
        "notice": NOTICE,
        "counts": {"cases": len(cases), "series": n_series, "excluded": len(dataset.excluded),
                   "inconsistent": inconsistent, "burned_in_unclear": burned_in,
                   "without_patient_key": no_key},
        "cases": cases,
        "excluded": [{"case_id": e.case_id, "reason": e.reason} for e in dataset.excluded],
    }


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def _case_row(c: ExportCase) -> list:
    ref = c.reference
    return [c.case_id, c.patient_key or "", c.suggested_split, ref["total"], ref["group"], ref["dominance"],
            ref["scoring_dominance"] or "", len(ref["lesions"]), len(c.series),
            sum(1 for s in c.series if s.kind == "cine"), c.rescored["consistent"]]


def _readme(dataset: ExportDataset, payload: dict) -> str:
    counts = payload["counts"]
    lines = [
        "MUSSA dataset export", "=" * 20, "", NOTICE, "",
        f"Created: {dataset.created}",
        f"Scoring engine: {dataset.engine_version} ({dataset.engine_source})",
        f"Cases: {counts['cases']}   series: {counts['series']}   "
        f"stills included: {'yes' if dataset.include_stills else 'no (cines only)'}   "
        f"images copied into this folder: {'yes' if payload['options']['images_copied'] else 'no (paths point into the app store)'}",
        "", "Files:", "  dataset.json  full data (format in docs/dataset-format.md)",
        "  cases.csv     one row per exported case", "  series.csv    one row per series", "",
        "What is deliberately not in this export: scorer names (only the confirming scorer's level),",
        "folder labels, original UIDs, MRNs, source file names and paths. Copied images keep only an",
        "allow-list of DICOM elements (remapped IDs, study date, geometry, pixels, cine timing, C-arm angles).",
        "The study date is kept; it is a quasi-identifier for the ethics review to judge.", "",
        "Split suggestion: train 70% / val 15% / test 15%, chosen from a hash of the patient key so that",
        "all cases of one patient share a split. With a small number of patients (for example one) the",
        "split is not meaningful.", "",
    ]
    warnings = []
    for c in dataset.cases:
        if not c.rescored["consistent"]:
            if c.rescored["total"] is None:
                warnings.append(f"WARNING: case {c.case_id}: the current engine now scores the confirmed form "
                                f"as incomplete or invalid. The reference ({c.reference['total']}) was kept "
                                f"as confirmed; please review it.")
            else:
                warnings.append(f"WARNING: case {c.case_id}: the current engine gives total "
                                f"{c.rescored['total']} but the confirmed reference is {c.reference['total']}. "
                                f"The reference was kept as confirmed; please review it.")
    if counts["burned_in_unclear"]:
        warnings.append(f"WARNING: {counts['burned_in_unclear']} series may contain burned-in patient text in "
                        f"the pixels (series.csv, column burned_in_unclear). Tag removal cannot strip it: look "
                        f"at those images before sharing anything.")
    if counts["without_patient_key"]:
        warnings.append(f"NOTE: {counts['without_patient_key']} case(s) have no patient key (no MRN in the "
                        f"files). Each is treated as its own patient for the split suggestion.")
    for e in dataset.excluded:
        warnings.append(f"NOT EXPORTED: case {e.case_id}: {e.reason}")
    if warnings:
        lines += ["Notes:"] + warnings + [""]
    return "\n".join(lines)


def _remove_stale_temp_folders(out_dir: Path) -> None:
    """Remove leftovers of an export that was killed. Only folders we recognise by name and marker."""
    for leftover in out_dir.parent.glob(f"{out_dir.name}.tmp-*"):
        if leftover.is_dir() and (leftover / TEMP_MARKER).exists():
            shutil.rmtree(leftover, ignore_errors=True)


def write_export(dataset: ExportDataset, library: Library, out_dir: Path, copy_images: bool = False,
                 progress: Callable[[int, int], bool] | None = None) -> ExportResult:
    """Write the dataset to a new folder. The folder is built next to the target and renamed into
    place only when complete, so a failure leaves nothing behind; a non-empty target is refused.
    `progress(done, total)` is called after each copied image; returning False cancels the export
    (ExportCancelled)."""
    out_dir = Path(out_dir)
    if not dataset.cases:
        raise ValueError("There are no confirmed cases to export.")
    if not out_dir.parent.is_dir():
        raise FileNotFoundError(f"The folder {out_dir.parent} does not exist.")
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        raise FileExistsError(f"{out_dir} already exists and is not empty; choose a new folder name.")
    _remove_stale_temp_folders(out_dir)
    tmp = out_dir.parent / f"{out_dir.name}.tmp-{secrets.token_hex(4)}"
    try:
        tmp.mkdir()
        (tmp / TEMP_MARKER).write_text("temporary MUSSA export folder; safe to delete", encoding="utf-8")
        hashes: dict[str, str] = {}
        if copy_images:
            (tmp / "images").mkdir()
            work = [(c, s) for c in dataset.cases for s in c.series]
            for done, (c, s) in enumerate(work, start=1):
                source = library.store_dir / f"{s.series_id}.dcm"
                if not source.exists():
                    raise FileNotFoundError(f"Series {s.series_id} of case {c.case_id} is missing from the store.")
                hashes[s.series_id] = write_clean_copy(source, tmp / "images" / f"{s.series_id}.dcm")
                if progress is not None and not progress(done, len(work)):
                    raise ExportCancelled("Export cancelled; nothing was written.")
        payload = _payload(dataset, copy_images, hashes)
        (tmp / "dataset.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
        _write_csv(tmp / "cases.csv", CASE_COLUMNS, [_case_row(c) for c in dataset.cases])
        _write_csv(tmp / "series.csv", SERIES_COLUMNS,
                   [[c.case_id, s.series_id, s.kind, s.view, s.frames, s.burned_in_unclear,
                     _series_path(s, copy_images)] for c in dataset.cases for s in c.series])
        (tmp / "README.txt").write_text(_readme(dataset, payload), encoding="utf-8")
        (tmp / TEMP_MARKER).unlink()
        if out_dir.exists():
            out_dir.rmdir()                      # an empty target folder is accepted
        os.replace(tmp, out_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    counts = payload["counts"]
    return ExportResult(folder=out_dir, cases=counts["cases"], series=counts["series"],
                        excluded=counts["excluded"], inconsistent=counts["inconsistent"],
                        images_copied=len(hashes), burned_in_unclear=counts["burned_in_unclear"])
