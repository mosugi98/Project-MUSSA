# Dataset Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export every confirmed case as a de-identified dataset (reference score and form data, plus references to its de-identified cine series) that a later AI step can read, without leaking scorer names, folder labels, original UIDs or source paths (spec build step 4).

**Architecture:** A Qt-free `cagsyntax.export` package builds an in-memory `ExportDataset` from the case store and the image library (`dataset.py`), assigns a patient-level split suggestion (`splits.py`) and writes it to a new folder (`writer.py`). `MainWindow` gets one action that asks for a folder and two options and calls the same function the tests call.

**Tech Stack:** Python 3.13, stdlib (`json`, `csv`, `hashlib`, `shutil`), pytest, PySide6 for the action only. No new dependencies.

**Spec:** `docs/specs/2026-11-20-cag-syntax-ai-design.md` (sections 2, 5.1, 5.3, 6, 7, 9 step 4).

## Global Constraints

- Export: confirmed cases as a dataset (de-identified image references plus form data and score) for Phase B (spec 5.3).
- Cine series only by default; stills are excluded unless the user asks for them (spec 5.3 and 3.1).
- No cloud processing; patient images stay on the hospital machine (spec 2). The export is a local folder; nothing is sent anywhere.
- De-identification happens on import, before anything is stored (spec 7). The export must not reintroduce identifiers: it never contains scorer names, folder labels, original UIDs, MRNs, source file names or source paths.
- Hold-out test cases keep all images of one patient in the same split (spec 6). The export therefore carries a patient key and a patient-level split suggestion.
- Labeled as decision support for research and teaching, not a certified medical device (spec 7).
- Engine output must match the official calculator before any clinical use (spec 8): the export re-scores each reference with the current engine and flags any difference.

## Decisions (my calls, for review)

- **What is exported:** every case that has a confirmed reference, using the confirmed snapshot (not any later edit). Unconfirmed cases are not exported.
- **Format:** one folder per export: `dataset.json` (full data), `cases.csv` and `series.csv` (flat tables for spreadsheets), `README.txt`, and `images/` only when copying is chosen. Written to a temporary sibling folder and renamed only when complete; an existing non-empty target is refused, never overwritten.
- **Image references, not copies, by default:** each series lists its path inside the app's de-identified store (`store/<series id>.dcm`, relative to the data folder). A "copy the de-identified images into the export" option writes them to `images/` with a SHA-256 for each file.
- **Scorers:** the export records only the confirming scorer's level, never names.
- **Folder labels are left out:** the label is typed by the user and may contain identifiers.
- **Study date is kept** (spec 5.1 keeps it); series descriptions are left out.
- **Split suggestion:** `train` 70%, `val` 15%, `test` 15%, chosen from a hash of the patient key, so the same patient always lands in the same split and repeat exports agree. With very few patients the split is not meaningful; the README says so.
- **Cases that cannot be exported** (no series left in the store, or only stills when stills are excluded) are listed in `excluded` with a reason, never silently dropped.
- **Engine check:** if the current engine gives a different total than the confirmed snapshot, the case is still exported with `consistent: false`, both totals and a README warning.

## Review Focus

1. The export must contain no scorer name, folder label, original UID, MRN, source path or source file name. Tested in Tasks 3 and 4 by scanning every written byte for planted identifiers.
2. A failed or interrupted export must leave no half-written folder, and an existing non-empty target must never be overwritten. Test in Task 4.
3. A confirmed case whose series were deleted from the viewer must be reported in `excluded`, not crash and not vanish. Test in Task 3.
4. A confirmed case whose engine re-score differs must be exported with `consistent: false`, not altered. Test in Task 3.
5. A confirmed study that has only stills must be excluded by default and included when stills are requested. Test in Task 3.

---

## File Structure

```
src/cagsyntax/export/__init__.py
src/cagsyntax/export/splits.py     # suggest_split(patient_key)
src/cagsyntax/export/dataset.py    # build_dataset(...) -> ExportDataset (pure, no file writing)
src/cagsyntax/export/writer.py     # write_export(...) -> ExportResult
src/cagsyntax/store.py             # modified: confirmed_cases()
src/cagsyntax/app.py               # modified: export action
docs/dataset-format.md             # the export format, for the next step
tests/test_splits.py, test_export_dataset.py, test_export_writer.py, test_export_app.py
```

---

### Task 1: Store accessor and split suggestion

**Files:**
- Modify: `src/cagsyntax/store.py`
- Create: `src/cagsyntax/export/__init__.py`, `src/cagsyntax/export/splits.py`
- Test: `tests/test_store.py` (append), `tests/test_splits.py`

**Interfaces:**
- Produces in `store.py`: `@dataclass ConfirmedCase(study_uid: str, mrn_hash: str, confirmation: Confirmation)` and `CaseStore.confirmed_cases() -> list[ConfirmedCase]` ordered by study uid (guarded like the other methods).
- Produces in `splits.py`: `SPLITS = ("train", "val", "test")` and `suggest_split(patient_key: str) -> str`: `bucket = int(sha256(("mussa-split:" + patient_key).encode()).hexdigest()[:8], 16) % 100`; bucket below 70 is `train`, below 85 `val`, otherwise `test`.

- [ ] **Step 1: Write failing tests.** Store: with two confirmed cases and one unconfirmed case, `confirmed_cases()` returns exactly the two, each with its `mrn_hash` (as given to `ensure_case`) and the confirmation snapshot, ordered by study uid; empty store gives `[]`. Splits: `suggest_split("a") == suggest_split("a")`; the result is always in `SPLITS`; over 2,000 distinct keys the shares are within 3 percentage points of 70/15/15; a key with a known hash lands in the expected split (compute one fixed example and assert it); different case ids of the same patient key give the same split (the function takes only the patient key).
- [ ] **Step 2: Run** `python -m pytest tests/test_splits.py tests/test_store.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `ConfirmedCase`, `confirmed_cases` (join `cases` and `confirmations`, reuse `confirmation()`), and `suggest_split`.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(export): confirmed_cases accessor and patient-level split suggestion`.

---

### Task 2: Series information per study

**Files:**
- Create: `src/cagsyntax/export/dataset.py` (first part)
- Test: `tests/test_export_dataset.py`

**Interfaces:**
- Consumes: `Library.entries()`, `read_header`, `SeriesHeader`.
- Produces: `@dataclass ExportSeries(series_id: str, kind: str, view: str, frames: int, study_date: str, store_file: str)` where `series_id` is the stored file's stem (the remapped SOP uid) and `store_file` is `"store/<series_id>.dcm"`; and `series_by_study(library: Library) -> dict[str, list[ExportSeries]]` keyed by remapped study uid, series ordered cines first then stills then by `series_id`; unreadable stored files are skipped.

- [ ] **Step 1: Write failing tests** using the factory (two series of one study with different angles, one still of the same study, one series of another study): grouping by study; order cines before stills; `view` equals the header's view label; `frames` is the frame count; `store_file` starts with `store/` and ends with `.dcm`; an unreadable stored file is skipped; the original SOP uid and the source file name appear nowhere in the result.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `ExportSeries` and `series_by_study`.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(export): per-study series information`.

---

### Task 3: Build the dataset

**Files:**
- Modify: `src/cagsyntax/export/dataset.py`
- Test: `tests/test_export_dataset.py` (append)

**Interfaces:**
- Consumes: `CaseStore.confirmed_cases()`, Task 2, `suggest_split`, `score_case`, `case_from_json`/`Case.from_dict`, `scoring.SOURCE`, `scoring.VERSION`.
- Produces:
  - `@dataclass ExportCase(case_id: str, patient_key: str, suggested_split: str, confirmed_at: str, confirmed_by_level: str, reference: dict, rescored: dict, series: list[ExportSeries])` where `reference` holds `total`, `group`, `dominance`, `scoring_dominance`, `lesions` (each `{"segments": [...], "total": float, "parts": [{"label": str, "points": float}]}`), `diffuse_segments` and the raw `form`; and `rescored` holds `total`, `group` and `consistent` (bool).
  - `@dataclass Exclusion(case_id: str, reason: str)`.
  - `@dataclass ExportDataset(created: str, engine_source: str, engine_version: str, include_stills: bool, cases: list[ExportCase], excluded: list[Exclusion])`.
  - `build_dataset(store: CaseStore, library: Library, include_stills: bool = False) -> ExportDataset`.

- [ ] **Step 1: Write failing tests**:
  - A confirmed case with two cines appears with the confirmation's total and group, `confirmed_by_level == "cardiologist"`, the patient key equal to the stored MRN hash and `suggested_split` equal to `suggest_split(patient_key)`; the reference lesions' parts sum to each lesion total; `rescored.consistent` is true.
  - Unconfirmed cases are absent.
  - Review Focus 1: scorer names, the folder label assigned in the library and the original UIDs do not appear in `dataclasses.asdict(dataset)` rendered as JSON.
  - Review Focus 3: a confirmed case whose series were all deleted is in `excluded` with a reason containing "no series"; the other cases are unaffected.
  - Review Focus 4: tamper the stored confirmation form so the engine now scores it differently (for example change the stored total in the snapshot): the case is exported with `consistent == False`, `reference.total` unchanged and `rescored.total` different.
  - Review Focus 5: a confirmed study with only a still is excluded by default (reason contains "still") and exported with `include_stills=True`; a study with cines and a still lists only the cines by default and both with `include_stills=True`.
  - A confirmed form that cannot be parsed is excluded with a reason, not a crash.
  - An empty store gives no cases and no exclusions.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `build_dataset`. The reference total, group and form come from the confirmation snapshot; the breakdown and the `rescored` values come from `score_case` on the snapshot form.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(export): build the dataset from confirmed cases`.

---

### Task 4: Write the export

**Files:**
- Create: `src/cagsyntax/export/writer.py`
- Test: `tests/test_export_writer.py`

**Interfaces:**
- Consumes: `ExportDataset`, `Library`.
- Produces: `@dataclass ExportResult(folder: Path, cases: int, series: int, excluded: int, inconsistent: int, images_copied: int)` and `write_export(dataset: ExportDataset, library: Library, out_dir: Path, copy_images: bool = False) -> ExportResult`. Files written: `dataset.json` (keys `format_version` = 1, `created`, `engine` with `source` and `version`, `options` with `include_stills` and `images_copied`, `notice`, `counts`, `cases`, `excluded`), `cases.csv` with the columns `case_id, patient_key, suggested_split, reference_total, reference_group, dominance, scoring_dominance, n_lesions, n_series, n_cines, consistent_with_engine`, `series.csv` with `case_id, series_id, kind, view, frames, path`, and `README.txt` (what the export is, the disclaimer, the split rule and its small-sample caveat, and a warning line for each inconsistent or excluded case). With `copy_images`, each series file is copied to `images/<series id>.dcm`, `path` points there, and `dataset.json` lists its `sha256`.

- [ ] **Step 1: Write failing tests**:
  - Files and columns: all four files exist; `cases.csv` and `series.csv` have exactly the columns above and one row per case and per series; `dataset.json` has `format_version == 1`, the engine source and version, counts matching the dataset, and the notice text containing "not a certified medical device".
  - Review Focus 1: plant a scorer name, a folder label, the factory's patient name and MRN and the original UID in the sources; scan every byte of every written file for each of them and for `"MRN12345"`, `"DOE"`, `"JOHN"`: none found. No file name or path in the export contains a source path (no drive letters, no `Data CAG`).
  - Review Focus 2: the target folder is created only when complete (simulate a write error by making `dataset.json` serialization fail with a monkeypatch; afterwards neither the target nor a temporary sibling exists); an existing non-empty target raises `FileExistsError` and its contents are unchanged; an existing empty folder is accepted.
  - `copy_images=True` copies one file per series, byte-identical to the store file, with a matching SHA-256 in `dataset.json`; without it `images/` does not exist and `path` starts with `store/`.
  - A repeat export of the same data gives identical `dataset.json` apart from `created`.
  - Warnings: an inconsistent case and an excluded case each produce a line in `README.txt`.
  - Zero cases: `write_export` raises `ValueError` with a clear message and creates nothing.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `write_export`** writing into `<out_dir>.tmp-<random>` next to the target and renaming it to `out_dir` at the end; remove the temporary folder on any error.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(export): write the dataset folder safely`.

---

### Task 5: App integration

**Files:**
- Modify: `src/cagsyntax/app.py`
- Test: `tests/test_export_app.py`

**Interfaces:**
- Consumes: `build_dataset`, `write_export`, `ExportResult`.
- Produces: `MainWindow.export_confirmed_cases(out_dir: Path, include_stills: bool = False, copy_images: bool = False) -> ExportResult | None` (returns `None` with a status message when scoring is unavailable, there are no confirmed cases, or the write fails; failures also go through `_failed` so a dialog is shown), and a toolbar action "Export dataset" that asks for a folder name inside a parent folder chosen with a file dialog, then two yes/no questions ("Include still images?", "Copy the de-identified images into the export?"), and shows a summary dialog with the counts, the number of inconsistent and excluded cases and the folder path.

- [ ] **Step 1: Write failing tests** (offscreen, `_confirm` and `_warn` replaced): end to end with two series of one study scored by a cardiologist and confirmed: `export_confirmed_cases(tmp / "out")` returns an `ExportResult` with 1 case and 2 series and the files exist; no confirmed cases gives `None` and the status bar says there is nothing to export; store unavailable gives `None`; an existing non-empty target gives `None` and a warning; `include_stills=True` and `copy_images=True` are passed through; the exported bytes contain none of the planted identifiers and none of the scorer's name; exporting does not change the case store or the series list.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the method and the action.
- [ ] **Step 4: Run** `python -m pytest -q`. Expected: all PASS.
- [ ] **Step 5: Manual check:** launch the app, confirm a reference, click Export dataset, open `dataset.json` and `cases.csv`.
- [ ] **Step 6: Commit** `feat(app): export confirmed cases`.

---

### Task 6: Documentation

**Files:**
- Create: `docs/dataset-format.md`; modify `docs/user-guide.md`, `docs/specs/2026-11-20-cag-syntax-ai-design.md`

- [ ] **Step 1: Write `docs/dataset-format.md`:** every file and field of the export, the split rule and its caveat, how to join `series.csv` to `cases.csv`, how to read a series (store path or copied image), and the privacy rules the export keeps.
- [ ] **Step 2: Update spec 5.3** with the decisions above and the user guide with an "Export for the AI step" section (what it does, the two options, where the files go, what is deliberately left out).
- [ ] **Step 3: Run** `python -m pytest -q`. Expected: all PASS.
- [ ] **Step 4: Commit** `docs: dataset export format and decisions`.

---

## Self-Review

- **Spec coverage:** export of confirmed cases with de-identified image references plus form data and score, cines only by default (5.3, 3.1) is Tasks 2 to 5; patient-level splits (6) is Task 1; no identifiers reintroduced (5.1, 7) is the scan tests in Tasks 3 and 4; the engine check (8) is the `rescored` field. Out of scope: any AI training or inference (spec step 5) and ethics paperwork.
- **Type consistency:** `ConfirmedCase` (Task 1) is used in Task 3; `ExportSeries` (Task 2) in Tasks 3 and 4; `ExportCase`, `Exclusion` and `ExportDataset` (Task 3) in Tasks 4 and 5; `ExportResult` (Task 4) in Task 5.
- **Open risks:** the split suggestion is only meaningful with many patients (the current data is one patient); the study date stays in the export, as the spec keeps it, and is a quasi-identifier for the ethics process to judge; the export references files in the app's store, so moving the data folder breaks the paths unless images are copied.
