# Scoring Form and Case Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a scorer open a case (one imported study) in the viewer, fill in the SYNTAX form on a segment picker, see the live score from the engine, save their entry, and let a cardiologist confirm one entry as the reference; report how often scorers differ from the confirmed version (spec build step 3).

**Architecture:** A Qt-free `CaseStore` (SQLite) holds users, cases, one entry per (case, scorer) and one confirmed snapshot per case. A Qt-free `form_state` module turns the engine's question rules into "which questions apply" and keeps answers consistent. Thin PySide6 widgets (`SegmentTree`, `ScoringPanel`) sit on those, and `MainWindow` gets a user selector, a Score action and a disagreement report.

**Tech Stack:** Python 3.13, stdlib `sqlite3`, PySide6, pytest. No new dependencies.

**Spec:** `docs/specs/2026-11-20-cag-syntax-ai-design.md` (sections 3, 5.2, 5.3, 7, 8, 9 step 3). Scoring engine: `src/cagsyntax/scoring/` (done in step 2).

## Global Constraints

- Scorers are residents and cardiologists; the tool records who scored each case and their experience level (spec 3).
- Reference label: the version confirmed by a cardiologist (spec 3). One confirmed entry per case, set by a cardiologist (spec 5.3).
- One record per case; multiple scorer entries per case (spec 5.3).
- Case store saves each scorer's entry, scorer identity and level, timestamps, and the confirmed version (spec 5 table).
- Disagreement tracking: the app reports how often scorers differ from the confirmed version, per scorer level (spec 5.3).
- A case with missing required fields is marked incomplete and gets no final score; the engine decides (spec 5.2).
- Python, PySide6, SQLite, Windows desktop, fully offline (spec 4); no cloud processing (spec 2).
- Access to the case store is limited to named users on the hospital machine (spec 7). The store holds no direct patient identifiers (only the MRN hash and the remapped study UID).
- Labeled as decision support for research and teaching, not a certified medical device (spec 7).
- Export of confirmed cases is step 4 and is not part of this plan.

## Decisions (my calls, for review)

- **What a case is:** one imported study, identified by the (remapped) `StudyInstanceUID` of its stored series. All series of a study belong to one case. The scorer opens a case from any of its series in the list.
- **Scorer identity:** named user profiles (name plus level `resident` or `cardiologist`) kept in the case store; the app asks for a user before scoring and remembers the last one. There is no password: access control is the Windows account on the hospital machine (spec 7). Only a `cardiologist` can confirm.
- **One live entry per scorer per case:** saving again updates that scorer's entry (with a new `saved_at`). Confirming copies a snapshot of the entry, so later edits do not change the confirmed version.
- **Incomplete and invalid entries can be saved as drafts** (status is stored); only a `complete` entry can be confirmed.
- **Disagreement** is measured on the final total and group against the confirmed snapshot, per scorer level, excluding the confirmed entry itself. Per-lesion or per-segment comparison is left for a later step.
- **No free-text comment field** in the form (spec lists none, and free text invites patient identifiers).
- Deleting series from the viewer does not delete cases or entries.

## Review Focus

1. Two scorers saving the same case must not overwrite each other, and one scorer saving twice must update, not duplicate. Test in Task 1.
2. A resident cannot confirm; an incomplete or invalid entry cannot be confirmed. Test in Task 1.
3. Editing an entry after it was confirmed must not change the confirmed snapshot. Test in Task 1.
4. Changing dominance, total occlusion or the side branch must never leave a stale answer that makes the case invalid without the scorer being able to see and fix it. Test in Tasks 3 and 6.
5. A corrupt or missing database file, or one written by a newer schema, must give a clear message, not a crash or silent data loss. Test in Task 1.

---

## File Structure

```
src/cagsyntax/store.py            # CaseStore, User, Entry, Confirmation  (Qt-free)
src/cagsyntax/report.py           # disagreement_report                    (Qt-free)
src/cagsyntax/form_state.py       # question applicability, clean_lesion, JSON  (Qt-free)
src/cagsyntax/cases.py            # studies_in_store                       (Qt-free)
src/cagsyntax/ui/segment_tree.py  # SegmentTree widget
src/cagsyntax/ui/scoring_panel.py # ScoringPanel widget
src/cagsyntax/ui/__init__.py
src/cagsyntax/app.py              # modified: user selector, Score action, report
tests/test_store.py, test_report.py, test_form_state.py, test_cases.py,
tests/test_segment_tree.py, test_scoring_panel.py, test_scoring_flow.py
```

---

### Task 1: Case store

**Files:**
- Create: `src/cagsyntax/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces:
  - `@dataclass User(id: int, name: str, level: str)`; levels are `"resident"` and `"cardiologist"`.
  - `@dataclass Entry(id: int, study_uid: str, user: User, form: dict, status: str, total: float | None, group: str | None, scoring_dominance: str | None, saved_at: str)`
  - `@dataclass Confirmation(entry_id: int, confirmed_by: User, confirmed_at: str, form: dict, status: str, total: float | None, group: str | None)`
  - `class StoreError(Exception)` (message is user-facing)
  - `class CaseStore: __init__(path: Path)`; `close()`; `add_user(name: str, level: str) -> User` (name trimmed, unique ignoring case, `ValueError` otherwise); `users() -> list[User]`; `ensure_case(study_uid: str, mrn_hash: str) -> None`; `save_entry(study_uid: str, user_id: int, form: dict, result: CaseResult) -> Entry` (upsert per case and user; stores `form`, `result.status`, `result.total`, `result.group`, `result.scoring_dominance`, the engine `VERSION`, ISO UTC `saved_at`); `entries(study_uid: str) -> list[Entry]`; `confirm(study_uid: str, entry_id: int, user_id: int) -> Confirmation` (`PermissionError` unless the user is a cardiologist; `ValueError` unless the entry belongs to the case and has status `complete`; replaces any earlier confirmation); `confirmation(study_uid: str) -> Confirmation | None`; `case_summaries() -> list[tuple[str, int, bool]]` (study uid, number of entries, has confirmation); `get_meta(key: str) -> str | None`; `set_meta(key: str, value: str) -> None`.
  - Schema version stored with `PRAGMA user_version = 1`; opening a store with a higher version raises `StoreError`.

- [ ] **Step 1: Write failing tests** with a `tmp_path` store and a helper that builds a `CaseResult` via `score_case`:
  - `add_user("Dr Ana", "cardiologist")` then `add_user("dr ana", "resident")` raises `ValueError`; an unknown level raises `ValueError`.
  - Review Focus 1: two users saving the same study give two entries; the same user saving twice gives one entry with the latest form and a later `saved_at`.
  - Review Focus 2: a resident `confirm` raises `PermissionError`; confirming an incomplete entry raises `ValueError`; confirming an entry of another case raises `ValueError`.
  - A cardiologist confirms a complete entry: `confirmation(uid)` has that entry's total, group and form; confirming a different entry replaces it (still one confirmation per case).
  - Review Focus 3: after confirming, the scorer saves a different form; `confirmation(uid).total` and `.form` are unchanged while `entries(uid)` shows the new total.
  - Round trip: `entries()` returns the form dict equal to what was saved, including `None` values.
  - Review Focus 5: opening a path holding random bytes raises `StoreError` mentioning the file name; a store created with `PRAGMA user_version = 99` raises `StoreError` mentioning "newer"; the file is not modified by the failed open; a missing parent folder is created.
  - `get_meta`/`set_meta` round trip and overwrite; `case_summaries` counts entries and confirmation.
  - Privacy: after saving entries, the raw database bytes contain none of the strings `"DOE"`, `"JOHN"`, `"MRN12345"`.
- [ ] **Step 2: Run** `python -m pytest tests/test_store.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `CaseStore`** with `sqlite3`: tables `users(id, name, name_key UNIQUE, level)`, `cases(study_uid PRIMARY KEY, mrn_hash)`, `entries(id, study_uid, user_id, form_json, status, total, grp, scoring_dominance, engine_version, saved_at, UNIQUE(study_uid, user_id))`, `confirmations(study_uid PRIMARY KEY, entry_id, confirmed_by, confirmed_at, form_json, status, total, grp)`, `meta(key PRIMARY KEY, value)`; foreign keys on; every write in a transaction.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(store): case store with scorers, entries and confirmation`.

---

### Task 2: Disagreement report

**Files:**
- Create: `src/cagsyntax/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `CaseStore`.
- Produces: `@dataclass LevelStats(level: str, compared: int, same_total: int, same_group: int, mean_abs_diff: float, max_abs_diff: float)` and `disagreement_report(store: CaseStore) -> list[LevelStats]` (one row for each level that has comparisons, ordered `resident` then `cardiologist`). For every case with a confirmation, every entry other than the confirmed entry with status `complete` is compared with the confirmation snapshot. Cases without a confirmation and non-complete entries are not counted.

- [ ] **Step 1: Write failing tests**: a store with two cases, a confirmed total of 20 (low) with resident entries of 20 (same), 24 (differs, group differs) and 18 (differs, group same), plus a cardiologist entry of 20; expected resident row `compared=3, same_total=1, same_group=2, mean_abs_diff=2.0, max_abs_diff=4.0`; the confirmed entry itself is excluded; an incomplete resident entry is excluded; a case without confirmation contributes nothing; an empty store returns `[]`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `disagreement_report`.**
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(report): disagreement with confirmed version per scorer level`.

---

### Task 3: Form state (question rules and consistency)

**Files:**
- Create: `src/cagsyntax/form_state.py`
- Test: `tests/test_form_state.py`

**Interfaces:**
- Consumes: `cagsyntax.scoring` (`Case`, `Lesion`, `validate` helpers `tri_bif_asked`, `beyond_asked`, `beyond_candidates`, `OSTIAL_SEGMENTS`, `weight`).
- Produces:
  - `applicable_questions(lesion: Lesion, dominance: str | None) -> set[str]` returning the field names that currently apply, from: `"first_segment"`, `"age_over_3_months"`, `"blunt_stump"`, `"bridging"`, `"beyond_first_visualized"`, `"side_branch"`, `"trifurcation"`, `"bifurcation"`, `"bifurcation_angle_lt70"`, `"aorto_ostial"`, `"length_gt20"`, plus the always-asked `"occlusion"`, `"severe_tortuosity"`, `"heavy_calcification"`, `"thrombus"`. Rules: occlusion sub-questions only when `occlusion is True`; `beyond_first_visualized` only when its main segment is marked and `beyond_asked`; trifurcation and bifurcation per `tri_bif_asked`; trifurcation answer above 0 removes `"bifurcation"` and the angle; angle only when `bifurcation` is a Medina letter; `aorto_ostial` only when a segment in `OSTIAL_SEGMENTS` is selected; `length_gt20` only when `occlusion is False`.
  - `clean_lesion(lesion: Lesion, dominance: str | None) -> Lesion` returning a copy where every answer that no longer applies is set back to `None` (and `first_segment` is cleared if it left `segments`), never touching answers that still apply.
  - `change_dominance(case: Case, dominance: str | None, scoring_dominance: str | None) -> Case` returning a copy with segments and diffuse segments that do not exist for the new scoring dominance removed, and every lesion cleaned; also returns which segments were removed via `removed_segments(before: Case, after: Case) -> list[str]` so the UI can tell the scorer.
  - `case_to_json(case: Case) -> str` and `case_from_json(text: str) -> Case` (round trip via `dataclasses.asdict` and `Case.from_dict`; raises `ValueError` on malformed text).

- [ ] **Step 1: Write failing tests**: an occlusion with side branch `"small"` has no `"trifurcation"`, `"bifurcation"` or angle in `applicable_questions`, with `"large"` it has the first two; trifurcation 2 removes `"bifurcation"`; bifurcation `"D"` adds the angle, `"none"` does not; ostial only with segment 6 selected; length only when `occlusion is False`; `beyond_first_visualized` absent when the first segment is 8 (single candidate) and present for first segment 2 under right dominance. Review Focus 4: `clean_lesion` on an occlusion that gets switched to `occlusion=False` clears `first_segment`, age, blunt stump, bridging, beyond and side branch; switching the side branch from `"large"` to `"no"` clears trifurcation, bifurcation and angle; removing the first segment from `segments` clears `first_segment` and `beyond_first_visualized`; answers that still apply are untouched; a cleaned lesion passes `validate` with no `*_not_asked` or `occlusion_fields_without_occlusion` errors. `change_dominance` from right to left removes segments 4 and 16 from a lesion and from diffuse segments and lists them in `removed_segments`; to co-dominant with no scoring table keeps all segments. JSON round trip equals the original; `case_from_json("{")` raises `ValueError`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement the four functions.**
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(form): question rules, stale-answer cleanup and JSON for the scoring form`.

---

### Task 4: Cases from the stored series

**Files:**
- Modify: `src/cagsyntax/dicom_import/models.py` (add `study_uid: str = ""` and `mrn_hash: str = ""` to `SeriesHeader`), `src/cagsyntax/dicom_import/reader.py` (`read_header` fills them from `StudyInstanceUID` and `PatientID`)
- Create: `src/cagsyntax/cases.py`
- Test: `tests/test_cases.py`, `tests/test_reader.py` (header test)

**Interfaces:**
- Produces: `@dataclass StudyInfo(study_uid: str, mrn_hash: str, series_count: int, cine_count: int)` and `studies_in_store(library: Library) -> dict[str, StudyInfo]` keyed by study uid, built from `read_header` of every stored series (skips unreadable files); `study_of(path: Path) -> tuple[str, str]` returning (study uid, mrn hash) for one stored file.

- [ ] **Step 1: Write failing tests**: a store with two series of one study and one series of another gives two `StudyInfo` with the right counts; `read_header` of an imported file returns the remapped study uid (not the original) and a 64-character MRN hash; a store file that cannot be read is skipped.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cases): group stored series into studies`.

---

### Task 5: Segment tree widget

**Files:**
- Create: `src/cagsyntax/ui/__init__.py`, `src/cagsyntax/ui/segment_tree.py`
- Test: `tests/test_segment_tree.py`

**Interfaces:**
- Produces: `class SegmentTree(QWidget)` with signal `selection_changed = Signal(list)` (list of segment ids in table order), `set_scoring_dominance(dominance: str | None)` (segments not applicable are not drawn or clickable), `set_selected(ids: list[str])`, `selected() -> list[str]`, `set_first_segment(id: str | None)` (drawn with a distinct outline), `segment_at(x: float, y: float) -> str | None` taking coordinates in the 560 x 440 logical canvas. Geometry: the 25 segment line coordinates from the web prototype (`web-calculator/index.html`, constant `GEO`), drawn with `QPainter`, scaled to the widget, a numbered circle at each segment midpoint, hit radius 14 logical pixels. Clicking toggles selection and emits `selection_changed`.

- [ ] **Step 1: Write failing offscreen tests**: `segment_at` at the midpoint of segment 6 returns `"6"` and in empty space returns `None`; with dominance `"left"`, `segment_at` at the midpoint of segment 4 returns `None` and with `"right"` returns `"4"`; segment 15 mirrors that; clicking (via `QTest.mouseClick` at the scaled midpoint) toggles selection and emits the signal with the new list in table order; `set_selected` with a segment not applicable to the dominance drops it; with no dominance set nothing is clickable.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `SegmentTree`.**
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): clickable coronary segment tree`.

---

### Task 6: Scoring panel

**Files:**
- Create: `src/cagsyntax/ui/scoring_panel.py`
- Test: `tests/test_scoring_panel.py`

**Interfaces:**
- Consumes: `SegmentTree`, `form_state`, `score_case`, `CaseResult`.
- Produces: `class ScoringPanel(QWidget)` with signal `changed = Signal()`; `set_case(case: Case) -> None`; `case() -> Case` (current form, already cleaned); `result() -> CaseResult` (live `score_case(case())`); `set_dominance(dominance: str | None, scoring_dominance: str | None = None) -> list[str]` (returns removed segments); `add_lesion() -> None`, `remove_lesion(index: int) -> None`, `select_lesion(index: int) -> None`; `toggle_segment(segment: str) -> None` (current lesion); `answer(field: str, value) -> None` (sets one answer on the current lesion then cleans stale answers); `toggle_diffuse(segment: str) -> None`; `is_enabled(field: str) -> bool` (whether the question applies); `status_text() -> str`. Widgets: dominance combo, scoring-table combo (enabled only for co-dominant), lesion list with add and remove (at most 12), `SegmentTree`, one control per question (enabled per `applicable_questions`), diffuse chips for visible segments, and a result area showing total, group, status, each issue message, and the per-lesion breakdown. The disclaimer "Educational tool, not a certified medical device." is always visible.

- [ ] **Step 1: Write failing offscreen tests**: right dominance, one lesion on segment 6 with every question answered "no" shows total 7.0 and group `low`; unanswered questions show status "incomplete" and list each missing question in the result text, with no total shown; Review Focus 4: after answering an occlusion with side branch "large" and a bifurcation, answering side branch "small" disables the trifurcation and bifurcation controls, `case()` has them as `None`, and `result().status` has no `*_not_asked` error; switching dominance from right to left drops segment 4 from the lesion, `set_dominance` returns `["4"]`, and the result text says which segment was removed; co-dominant with no scoring table shows incomplete and the scoring-table combo enabled, choosing left scores with the left table; `add_lesion` stops at 12; `remove_lesion` re-indexes; `is_enabled("aorto_ostial")` is true only with segment 6 selected; the disclaimer text is present.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `ScoringPanel`** keeping all rules in `form_state` and the engine; the widgets only reflect them.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): scoring panel with live engine result`.

---

### Task 7: Main window integration

**Files:**
- Modify: `src/cagsyntax/app.py`, `Run MUSSA.bat` (no change expected)
- Test: `tests/test_scoring_flow.py`

**Interfaces:**
- Consumes: everything above. `MainWindow(data_dir)` gains `store: CaseStore` (file `data_dir/cases.sqlite`), `user_combo` (current scorer, remembered via `store.set_meta("last_user_id", ...)`), `add_user(name, level) -> User`, `current_user() -> User | None`, `score_selected_case() -> bool` (opens the panel for the study of the selected series, loading the current user's saved entry if any; returns False with a status message when no series is selected or no user is chosen), `save_entry() -> Entry | None`, `confirm_entry(entry_id: int) -> Confirmation | None`, `show_disagreements() -> str` (text of the report), and a toolbar with "Add user", "Score case", "Save score", "Confirm as reference", "Disagreements". A badge in the series list marks series whose study has a confirmed score (`[scored]`).

- [ ] **Step 1: Write failing tests** (offscreen, factory DICOM through `import_from`, `win._confirm` overridden where a prompt would appear):
  - No user: `score_selected_case()` is False and the status bar asks for a user; after `add_user("Dr Ana", "cardiologist")` it is True and the panel shows the study.
  - End to end: import two series of one study, select a row, set dominance right, add a lesion on segment 6 with all answers "no", `save_entry()` stores a complete entry with total 7.0 for that study; reopening the window and `score_selected_case()` shows the saved form.
  - Two users score the same study; each entry is kept; the resident's `confirm_entry` returns None with a message, the cardiologist's confirms and the series row shows `[scored]`.
  - `show_disagreements()` after a resident entry of 9.0 and a confirmed 7.0 contains "resident", "1", and the difference.
  - Deleting the series and reimporting keeps the saved entry for the same study (spec: cases are independent of the viewer list).
  - Privacy: the bytes of `cases.sqlite` after the flow contain none of `"DOE"`, `"JOHN"`, `"MRN12345"`.
  - A corrupt `cases.sqlite` at startup shows a clear message and the viewer still opens with scoring disabled (Review Focus 5).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement the integration.** Keep each action as a public method that the toolbar calls, so tests need no dialogs.
- [ ] **Step 4: Run** `python -m pytest -q`. Expected: all PASS.
- [ ] **Step 5: Manual check:** launch the app, add a user, import `Data CAG`, score the study on a few segments, save, add a second user and compare.
- [ ] **Step 6: Commit** `feat(app): score cases, save entries, confirm and report disagreements`.

---

### Task 8: Documentation

**Files:**
- Modify: `docs/specs/2026-11-20-cag-syntax-ai-design.md`; create `docs/user-guide.md`

- [ ] **Step 1: Update spec sections 5.2 and 5.3** with the decisions above (case = study, scorer profiles, snapshot on confirmation, disagreement definition, no comment field).
- [ ] **Step 2: Write `docs/user-guide.md`**: how to add a user, score a case, save, confirm, read the disagreement report, and where data lives (`C:\Users\<you>\MUSSA-data`), with the disclaimer.
- [ ] **Step 3: Run** `python -m pytest -q`. Expected: all PASS.
- [ ] **Step 4: Commit** `docs: scoring form and case store decisions and user guide`.

---

## Self-Review

- **Spec coverage:** scorers with level and timestamps, one record per case with several entries, one confirmed entry set by a cardiologist, and the disagreement report (5.3) map to Tasks 1, 2 and 7; the form inputs of 5.2 (dominance incl. co-dominant, 25 segments, all lesion features) to Tasks 3, 5 and 6; incomplete cases with no final score to Task 6; access and no patient identifiers (7) to the privacy tests in Tasks 1 and 7. Dataset export (5.3, step 4) and Phase B are out of scope.
- **Type consistency:** `CaseStore`, `User`, `Entry`, `Confirmation`, `LevelStats`, `StudyInfo` are defined in Tasks 1, 2 and 4 and used unchanged in Tasks 6 and 7; the form functions are defined in Task 3 and consumed in Task 6.
- **Proportion:** each task names signatures, test cases and values; bodies are left to the implementer.
- **Open risks:** the segment tree geometry comes from the web prototype and has never been checked against a real angiogram view (a visual check is part of Task 7 Step 5); the disagreement measure uses totals only, so two scorers who reach the same total with different lesions count as agreeing.
