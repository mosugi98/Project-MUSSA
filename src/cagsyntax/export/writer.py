from __future__ import annotations

import csv
import hashlib
import json
import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..library import Library
from .dataset import ExportCase, ExportDataset

FORMAT_VERSION = 1
NOTICE = ("De-identified research data exported from MUSSA. Educational tool, not a certified medical "
          "device. Not for clinical decisions.")
CASE_COLUMNS = ["case_id", "patient_key", "suggested_split", "reference_total", "reference_group",
                "dominance", "scoring_dominance", "n_lesions", "n_series", "n_cines",
                "consistent_with_engine"]
SERIES_COLUMNS = ["case_id", "series_id", "kind", "view", "frames", "path"]


@dataclass
class ExportResult:
    folder: Path
    cases: int
    series: int
    excluded: int
    inconsistent: int
    images_copied: int


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _series_path(series, copy_images: bool) -> str:
    return f"images/{series.series_id}.dcm" if copy_images else series.store_file


def _payload(dataset: ExportDataset, copy_images: bool, hashes: dict[str, str]) -> dict:
    cases = []
    for c in dataset.cases:
        series = []
        for s in c.series:
            item = {"series_id": s.series_id, "kind": s.kind, "view": s.view, "frames": s.frames,
                    "study_date": s.study_date, "path": _series_path(s, copy_images)}
            if copy_images:
                item["sha256"] = hashes[s.series_id]
            series.append(item)
        cases.append({"case_id": c.case_id, "patient_key": c.patient_key,
                      "suggested_split": c.suggested_split, "confirmed_at": c.confirmed_at,
                      "confirmed_by_level": c.confirmed_by_level, "reference": c.reference,
                      "rescored": c.rescored, "series": series})
    inconsistent = sum(1 for c in dataset.cases if not c.rescored["consistent"])
    n_series = sum(len(c.series) for c in dataset.cases)
    return {
        "format_version": FORMAT_VERSION, "created": dataset.created,
        "engine": {"source": dataset.engine_source, "version": dataset.engine_version},
        "options": {"include_stills": dataset.include_stills, "images_copied": copy_images},
        "notice": NOTICE,
        "counts": {"cases": len(cases), "series": n_series, "excluded": len(dataset.excluded),
                   "inconsistent": inconsistent},
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
    return [c.case_id, c.patient_key, c.suggested_split, ref["total"], ref["group"], ref["dominance"],
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
        "folder labels, original UIDs, MRNs, source file names and paths.", "",
        "Split suggestion: train 70% / val 15% / test 15%, chosen from a hash of the patient key so that",
        "all cases of one patient share a split. With a small number of patients (for example one) the",
        "split is not meaningful.", "",
    ]
    warnings = []
    for c in dataset.cases:
        if not c.rescored["consistent"]:
            warnings.append(f"WARNING: case {c.case_id}: the current engine gives total "
                            f"{c.rescored['total']} but the confirmed reference is {c.reference['total']}. "
                            f"The reference was kept as confirmed; please review it.")
    for e in dataset.excluded:
        warnings.append(f"NOT EXPORTED: case {e.case_id}: {e.reason}")
    if warnings:
        lines += ["Notes:"] + warnings + [""]
    return "\n".join(lines)


def write_export(dataset: ExportDataset, library: Library, out_dir: Path, copy_images: bool = False) -> ExportResult:
    """Write the dataset to a new folder. The folder is built next to the target and renamed into
    place only when complete, so a failure leaves nothing behind; a non-empty target is refused."""
    out_dir = Path(out_dir)
    if not dataset.cases:
        raise ValueError("There are no confirmed cases to export.")
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        raise FileExistsError(f"{out_dir} already exists and is not empty; choose a new folder name.")
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_dir.parent / f"{out_dir.name}.tmp-{secrets.token_hex(4)}"
    try:
        tmp.mkdir()
        hashes: dict[str, str] = {}
        if copy_images:
            (tmp / "images").mkdir()
            for c in dataset.cases:
                for s in c.series:
                    target = tmp / "images" / f"{s.series_id}.dcm"
                    shutil.copyfile(library.store_dir / f"{s.series_id}.dcm", target)
                    hashes[s.series_id] = _sha256(target)
        payload = _payload(dataset, copy_images, hashes)
        (tmp / "dataset.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
        _write_csv(tmp / "cases.csv", CASE_COLUMNS, [_case_row(c) for c in dataset.cases])
        _write_csv(tmp / "series.csv", SERIES_COLUMNS,
                   [[c.case_id, s.series_id, s.kind, s.view, s.frames, _series_path(s, copy_images)]
                    for c in dataset.cases for s in c.series])
        (tmp / "README.txt").write_text(_readme(dataset, payload), encoding="utf-8")
        if out_dir.exists():
            out_dir.rmdir()                      # an empty target folder is accepted
        os.replace(tmp, out_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    counts = payload["counts"]
    return ExportResult(folder=out_dir, cases=counts["cases"], series=counts["series"],
                        excluded=counts["excluded"], inconsistent=counts["inconsistent"],
                        images_copied=len(hashes))
