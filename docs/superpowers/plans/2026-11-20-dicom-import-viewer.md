# DICOM Import, De-identification and Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import XA cine DICOM files, de-identify them before anything is stored, label each view from C-arm angles, and play them in a desktop viewer (step 1 of the spec's build order).

**Architecture:** A pure-Python `dicom_import` package (reader, view labeling, de-identification, import pipeline) with no Qt dependency, and a `viewer` package split into Qt-free playback state (`CinePlayer`) and a thin PySide6 widget. Later steps (scoring engine, case store) will consume `ImportResult` and the stored de-identified files.

**Tech Stack:** Python 3.13, pydicom, numpy, PySide6 6.11, pytest (already installed except pydicom).

**Spec:** `docs/specs/2026-11-20-cag-syntax-ai-design.md` (sections 3, 5.1, 8, 9 step 1)

## Global Constraints

- Python + PySide6 + SQLite, Windows desktop, runs fully offline (spec section 4). No network calls anywhere.
- De-identification happens on import, before anything is stored (spec section 7).
- Strip patient name, ID, birth date and other direct identifiers; store a salted hash of the MRN so repeat cases can be linked (spec 5.1).
- Keep study date, modality, series description and positioner angles (spec 5.1).
- Non-XA DICOM (for example the X-Ray Radiation Dose SR) is rejected on import with a clear message; unsupported or corrupt files produce a visible error, never a silent skip (spec 3, 5.1).
- A scan test checks the stored output for leftover identifiers (spec 5.1).
- Positioner angles (primary and secondary) are read to label each view (spec 5).

## Review Focus

1. Compressed transfer syntax with no decoder installed: expected a clear "cannot decode" rejection, not a crash. Test in Task 2.
2. XA file with no positioner angles: expected to import with view label `"Unknown view"`, not be rejected. Test in Task 3.
3. Burned-in patient text in the pixels (`BurnedInAnnotation = YES`): expected an import warning that pixels may contain identifiers, since pixel text cannot be stripped by tag removal. Test in Task 4.
4. Importing the same file twice: expected to be reported as already imported, with no duplicate stored. Test in Task 5.
5. A folder containing a zero-byte file, a non-DICOM file and valid XA files: expected the valid ones imported and each bad one listed with its own message. Test in Task 5.

---

## File Structure

```
pyproject.toml
src/cagsyntax/__init__.py
src/cagsyntax/dicom_import/__init__.py
src/cagsyntax/dicom_import/models.py      # XASeries, ImportResult dataclasses, ImportRejected
src/cagsyntax/dicom_import/reader.py      # read_xa(path) -> XASeries
src/cagsyntax/dicom_import/views.py       # label_view(primary, secondary) -> str
src/cagsyntax/dicom_import/deidentify.py  # deidentify, hash_mrn, scan_identifiers, get_or_create_salt
src/cagsyntax/dicom_import/importer.py    # import_path(src, store_dir, salt)
src/cagsyntax/viewer/__init__.py
src/cagsyntax/viewer/player.py            # CinePlayer (no Qt)
src/cagsyntax/viewer/widget.py            # CineWidget (PySide6)
src/cagsyntax/app.py                      # main window + entry point
tests/dicom_factory.py                    # make_xa(...) synthetic DICOM builder
tests/test_*.py
```

---

### Task 1: Project scaffold and synthetic DICOM factory

**Files:**
- Create: `pyproject.toml`, `src/cagsyntax/__init__.py`, `src/cagsyntax/dicom_import/__init__.py`, `tests/dicom_factory.py`, `tests/test_factory.py`
- Copy: spec to `docs/specs/2026-11-20-cag-syntax-ai-design.md`

**Interfaces:**
- Produces: `make_xa(path: Path, *, frames: int = 5, rows: int = 64, cols: int = 64, primary: float | None = 30.0, secondary: float | None = 20.0, mrn: str = "MRN12345", name: str = "DOE^JOHN", sop_class: str = XA_SOP, burned_in: bool = False, frame_time_ms: float | None = 66.7) -> Path` writing a valid multi-frame uint8 XA file, and constants `XA_SOP = "1.2.840.10008.5.1.4.1.1.12.1"`, `DOSE_SR_SOP = "1.2.840.10008.5.1.4.1.1.88.67"`. Later tasks import these from `tests.dicom_factory`.

- [ ] **Step 1: `git init`, install deps** (`python -m pip install pydicom`), create `pyproject.toml` (package under `src/`, pytest `pythonpath = ["src", "."]`), copy the spec in.
- [ ] **Step 2: Write failing test** `test_make_xa_roundtrip`: write with `make_xa`, read with `pydicom.dcmread`; assert `ds.NumberOfFrames == 5`, `ds.pixel_array.shape == (5, 64, 64)`, `ds.PositionerPrimaryAngle == 30.0`, `ds.PatientID == "MRN12345"`.
- [ ] **Step 3: Run** `python -m pytest tests/test_factory.py -v`. Expected: FAIL (module missing).
- [ ] **Step 4: Implement `make_xa`** with `pydicom.dataset.FileDataset`, Explicit VR Little Endian, `Modality="XA"`, random uint8 pixels from a seeded numpy generator, `FrameTime` set only if `frame_time_ms` is not None, angle tags omitted when `None`, `BurnedInAnnotation` "YES"/"NO" per `burned_in`, plus `StudyDate`, `SeriesDescription="LAD cine"`, `PatientBirthDate`, `AccessionNumber`, `ReferringPhysicianName`, `InstitutionName` so de-identification has something to strip.
- [ ] **Step 5: Run test.** Expected: PASS.
- [ ] **Step 6: Commit** `chore: scaffold project and synthetic XA factory`.

---

### Task 2: XA reader with rejection rules

**Files:**
- Create: `src/cagsyntax/dicom_import/models.py`, `src/cagsyntax/dicom_import/reader.py`
- Test: `tests/test_reader.py`

**Interfaces:**
- Consumes: `make_xa`, `XA_SOP`, `DOSE_SR_SOP`.
- Produces in `models.py`: `class ImportRejected(Exception)` (message is user-facing); `@dataclass XASeries: dataset: pydicom.Dataset, frames: np.ndarray  # shape (n, rows, cols) uint8/uint16, fps: float, primary_angle: float | None, secondary_angle: float | None, sop_instance_uid: str, source: Path`. In `reader.py`: `read_xa(path: Path) -> XASeries`.

- [ ] **Step 1: Write failing tests**, each asserting exact outcomes:
  - `test_reads_valid_xa`: frames shape `(5, 64, 64)`, `fps == pytest.approx(1000/66.7)`, angles `30.0` / `20.0`.
  - `test_missing_frame_time_defaults_to_15_fps`.
  - `test_rejects_dose_sr`: `pytest.raises(ImportRejected, match="not an XA")` using `sop_class=DOSE_SR_SOP`.
  - `test_rejects_corrupt_file`: file of random bytes → `ImportRejected` matching `"not a valid DICOM"`.
  - `test_rejects_zero_byte_file` → `ImportRejected` matching `"empty"`.
  - `test_rejects_compressed_without_decoder` (Review Focus 1): rewrite a factory file's `file_meta.TransferSyntaxUID` to JPEG Lossless `1.2.840.10008.1.2.4.70` with raw pixel data; expect `ImportRejected` matching `"cannot decode"`.
- [ ] **Step 2: Run** `python -m pytest tests/test_reader.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `read_xa`.** Accept SOP classes `1.2.840.10008.5.1.4.1.1.12.1` and `1.2.840.10008.5.1.4.1.1.12.1.1` only; promote 2D pixel arrays to `(1, r, c)`; fps from `FrameTime` (ms) else `CineRate` else 15.0; wrap pydicom and pixel-decode exceptions into `ImportRejected` with the messages above.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: read XA series and reject non-XA or unreadable files`.

---

### Task 3: View labeling from C-arm angles

**Files:**
- Create: `src/cagsyntax/dicom_import/views.py`
- Test: `tests/test_views.py`

**Interfaces:**
- Produces: `label_view(primary: float | None, secondary: float | None) -> str`. Convention (DICOM): positive primary = LAO, negative = RAO; positive secondary = CRAN, negative = CAUD. Format `"LAO 30 CRAN 20"`, angles rounded to whole degrees, each side omitted when its angle rounds to 0 (`"AP"` if both 0), and `"Unknown view"` when either value is `None`.

- [ ] **Step 1: Write failing tests** (parametrized): `(30, 20) -> "LAO 30 CRAN 20"`, `(-45, -25) -> "RAO 45 CAUD 25"`, `(0, 0) -> "AP"`, `(0.4, 30) -> "CRAN 30"`, `(None, 20) -> "Unknown view"`, `(30, None) -> "Unknown view"`. (Review Focus 2.)
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `label_view`.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: label views from positioner angles`.

Note for the review stop: the sign convention can differ by vendor export. Confirm against a real cath-lab file before relying on labels.

---

### Task 4: De-identification, MRN hashing and identifier scan

**Files:**
- Create: `src/cagsyntax/dicom_import/deidentify.py`
- Test: `tests/test_deidentify.py`

**Interfaces:**
- Consumes: `make_xa`, `XASeries`.
- Produces: `get_or_create_salt(data_dir: Path) -> bytes` (32 random bytes stored in `data_dir/salt.key`, created once and reused); `hash_mrn(mrn: str, salt: bytes) -> str` (hex HMAC-SHA256, stable, case and whitespace normalized); `deidentify(ds: pydicom.Dataset, salt: bytes) -> tuple[pydicom.Dataset, str, list[str]]` returning a copy with identifiers removed, the MRN hash, and a list of warnings; `scan_identifiers(ds: pydicom.Dataset, forbidden: list[str]) -> list[str]` returning the tags or values where any forbidden string still appears, including inside private tags and nested sequences.

- [ ] **Step 1: Write failing tests:**
  - `test_strips_direct_identifiers`: after `deidentify`, `PatientName`, `PatientID`, `PatientBirthDate`, `PatientAddress`, `OtherPatientIDs`, `AccessionNumber`, `ReferringPhysicianName`, `OperatorsName`, `InstitutionName`, `StudyID` are empty or absent.
  - `test_keeps_study_date_modality_series_description_angles`.
  - `test_removes_private_tags`.
  - `test_scan_finds_no_identifiers_after_deidentify`: `scan_identifiers(out, ["DOE", "MRN12345", "JOHN"]) == []`, and `test_scan_detects_leak` returns non-empty for the original dataset.
  - `test_hash_is_stable_and_salted`: same input and salt equal; different salt differs; `"mrn12345 "` equals `"MRN12345"`; the hash does not contain the MRN.
  - `test_salt_persisted`: two calls on the same directory return identical bytes.
  - `test_burned_in_annotation_warns` (Review Focus 3): warning list contains a string with `"burned-in"` when `BurnedInAnnotation == "YES"`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Use `Dataset.walk` / `remove_private_tags`, deep copy the input, and have `deidentify` set `PatientIdentityRemoved = "YES"`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: de-identify datasets and hash MRN with a local salt`.

---

### Task 5: Import pipeline (file or folder to store)

**Files:**
- Create: `src/cagsyntax/dicom_import/importer.py`, `src/cagsyntax/dicom_import/models.py` (add `ImportResult`)
- Test: `tests/test_importer.py`

**Interfaces:**
- Consumes: `read_xa`, `label_view`, `deidentify`, `scan_identifiers`.
- Produces: `@dataclass ImportedItem: stored_path: Path, sop_instance_uid: str, mrn_hash: str, view_label: str, study_date: str, series_description: str, warnings: list[str]`; `@dataclass ImportResult: imported: list[ImportedItem], skipped_duplicates: list[Path], rejected: list[tuple[Path, str]]`; `import_path(src: Path, store_dir: Path, salt: bytes) -> ImportResult`. Stored file name is `<sop_instance_uid>.dcm`. A stored file must pass `scan_identifiers` against the source name and MRN, or the import of that file is rejected with `"de-identification check failed"` and nothing is written.

- [ ] **Step 1: Write failing tests:**
  - `test_imports_single_file`: one valid XA → one `ImportedItem`, stored file exists, reloaded copy has empty `PatientName`, `view_label == "LAO 30 CRAN 20"`.
  - `test_stored_output_has_no_identifiers`: scan the stored file for `"DOE"`, `"JOHN"`, `"MRN12345"` → empty.
  - `test_duplicate_import_is_skipped` (Review Focus 4): second call lists the file in `skipped_duplicates`, and the store holds exactly one file.
  - `test_mixed_folder` (Review Focus 5): folder with 2 valid XA, 1 zero-byte, 1 `notes.txt`, 1 dose SR → `len(imported) == 2`, `len(rejected) == 3`, every rejected entry has a non-empty message, none silently skipped.
  - `test_same_mrn_same_hash_across_files`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `import_path`.** Walk the folder recursively; for each file call `read_xa`, then `deidentify`, then write; catch `ImportRejected` per file and record it.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: import files and folders into a de-identified store`.

---

### Task 6: CinePlayer (Qt-free playback state)

**Files:**
- Create: `src/cagsyntax/viewer/player.py`
- Test: `tests/test_player.py`

**Interfaces:**
- Produces: `class CinePlayer` with `__init__(frame_count: int, fps: float)`, properties `index: int`, `playing: bool`, `interval_ms: int`; methods `play()`, `pause()`, `toggle()`, `step(delta: int)` (clamps to `[0, frame_count - 1]`), `seek(i: int)`, `tick()` (advances one frame when playing and wraps to 0 at the end). `interval_ms == round(1000 / fps)`.

- [ ] **Step 1: Write failing tests:** `step(1)` from 0 gives 1; `step(-1)` at 0 stays 0; `step` past end clamps to `frame_count - 1`; `tick()` while paused does not move; `tick()` while playing at last frame wraps to 0; `seek(99)` clamps; `interval_ms == 67` for `fps=15`; a single-frame series ticks and steps without error.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `CinePlayer`.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: add Qt-free cine playback state`.

---

### Task 7: Viewer widget and main window

**Files:**
- Create: `src/cagsyntax/viewer/widget.py`, `src/cagsyntax/app.py`
- Test: `tests/test_widget.py`

**Interfaces:**
- Consumes: `XASeries`, `CinePlayer`, `import_path`, `get_or_create_salt`, `label_view`.
- Produces: `class CineWidget(QWidget)` with `set_series(series: XASeries, view_label: str) -> None`, play/pause button, frame slider, step buttons, mouse-wheel zoom (clamped 0.25x to 8x), drag to pan, and a label showing `view_label` and `frame i / n`; `class MainWindow(QMainWindow)` with "Import file" and "Import folder" actions that run `import_path` into `<data_dir>/store`, show a summary dialog listing imported, duplicate and rejected files with messages and warnings, and load the imported items into a list so a selected item plays in `CineWidget`; `main() -> None` entry point. Frames are window-leveled to 8-bit for display (min-max per series).

- [ ] **Step 1: Write failing offscreen test** (`QT_QPA_PLATFORM=offscreen`): build `CineWidget`, call `set_series` with a factory-made series, assert the frame label reads `"frame 1 / 5"`, click step-forward and assert `"frame 2 / 5"`, assert zoom stays within `[0.25, 8.0]` after 50 wheel events.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement widget and window.** Use a `QTimer` driven by `CinePlayer.interval_ms`; convert frames with `QImage` format `Grayscale8`.
- [ ] **Step 4: Run** `python -m pytest -v`. Expected: all tests PASS.
- [ ] **Step 5: Manual check:** run `python -m cagsyntax.app`, import a factory-made file, confirm playback, stepping, zoom and the rejection summary for a dose SR file.
- [ ] **Step 6: Commit** `feat: add cine viewer and import window`.

---

## Self-Review

- **Spec coverage:** section 5.1 (strip identifiers, salted MRN hash, keep study date/modality/series description/angles, scan test, visible errors) and section 3 (XA only, dose SR rejected) map to Tasks 2, 4 and 5; viewer (cine, frame stepping, zoom) to Tasks 6 and 7; angle labeling to Task 3. Section 8's DICOM import test list (valid XA, non-XA including dose SR, corrupt, missing-angle) is covered by Tasks 2, 3 and 5. De-identification scan is in Tasks 4 and 5.
- **Not in this plan:** the scoring engine, form, case store, dataset export and AI (spec steps 2 to 5), and the spec's open items (ethics approval, dataset, export location).
- **Open risks for the review stop:** vendor sign conventions for angles; real exports may use compressed transfer syntaxes, which need an extra decoder package (`pylibjpeg`) once a real file is available; burned-in text cannot be removed by tag stripping.
