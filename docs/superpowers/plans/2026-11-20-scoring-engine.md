# SYNTAX Scoring Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pure-Python SYNTAX Score I engine (case in, score and per-lesion breakdown out) whose output matches the official calculator on hundreds of generated cases.

**Architecture:** `cagsyntax.scoring` holds the official tables (`tables.py`), plain dataclasses (`model.py`), a validator (`validate.py`) and the scorer (`engine.py`). No Qt, no I/O, no AI. Correctness is proven by an oracle: the official calculator's own JavaScript is run locally in a locked-down Node `vm` sandbox over generated cases, and its totals are saved as `tests/scoring/golden.json`; the Python engine must match every one.

**Tech Stack:** Python 3.13, pytest, Node.js (oracle only; already installed).

**Spec:** `docs/specs/2026-11-20-cag-syntax-ai-design.md` (sections 5.2, 8, 9 step 2)

## Global Constraints

- Rules follow SYNTAX I: lesions with 50% or more diameter stenosis in vessels of 1.5 mm or larger (spec 5.2).
- Inputs: coronary dominance (right, left, co-dominant), segment selection (the full 25 sub-segments: 1, 2, 3, 4, 5, 6, 7, 8, 9, 9a, 10, 10a, 11, 12, 12a, 12b, 13, 14, 14a, 14b, 15, 16, 16a, 16b, 16c), and per-lesion features: total occlusion (with sub-features), bifurcation (type and angle), trifurcation, aorto-ostial, severe tortuosity, length over 20 mm, heavy calcification, thrombus, diffuse disease or small vessels.
- Output: total score, group (low 22 or below, intermediate 23 to 32, high 33 or above), per-lesion breakdown (spec 5.2).
- Weights and modifiers come from the official published tables, not memory; the source and version used are recorded in code (spec 5.2). Source: official calculator v2.28, `https://syntaxscore.org/calculator/syntaxscore/javascript/frameset.js`.
- The engine rejects impossible combinations; a case with missing required fields is marked incomplete and gets no final score (spec 5.2).
- The engine is a pure function with no UI and no AI (spec section 5 table).
- Engine output must match the official calculator on every test case before any clinical use (spec section 8).
- **Decision (co-dominance):** the official score has no co-dominant table. The case records `dominance` as right, left or co-dominant; when co-dominant, `scoring_dominance` (right or left) must be chosen by the scorer, and both are shown in the result.
- **Decision (verification):** official JS is used only to generate golden numbers. The downloaded official files live in `tools/oracle/official/` (git-ignored, never committed or shipped); only `golden.json` is committed.

## Review Focus

1. A case with zero lesions: expected status `incomplete` and no total, never a total of 0. Test in Task 2.
2. A lesion with no segments selected: expected `incomplete`. Test in Task 2.
3. A segment that does not apply to the scoring dominance (for example 15 under right dominance, or 4 under left): expected a validation issue, never silently dropped. Test in Task 2.
4. Co-dominant with no scoring table chosen: expected `incomplete`. Test in Task 2.
5. Thirteen lesions: expected a validation issue (the official calculator stops at 12). Test in Task 2.

---

## File Structure

```
src/cagsyntax/scoring/__init__.py     # re-exports score_case and the dataclasses
src/cagsyntax/scoring/tables.py       # SEGMENTS, MEDINA, VISUALIZED_HELP, OSTIAL_SEGMENTS, SOURCE, VERSION
src/cagsyntax/scoring/model.py        # Lesion, Case, Part, LesionResult, CaseResult, Issue
src/cagsyntax/scoring/validate.py     # validate(case) -> list[Issue]
src/cagsyntax/scoring/engine.py       # score_case(case) -> CaseResult
tools/oracle/fetch_official.py        # downloads official files into tools/oracle/official/
tools/oracle/driver.mjs               # runs the official JS in a node:vm sandbox over JSON cases
tools/oracle/generate_golden.py       # seeded case generator + runs driver -> tests/scoring/golden.json
tests/scoring/test_tables.py, test_validate.py, test_engine.py, test_golden.py, golden.json
```

---

### Task 1: Official tables

**Files:**
- Create: `src/cagsyntax/scoring/__init__.py`, `src/cagsyntax/scoring/tables.py`
- Test: `tests/scoring/test_tables.py`

**Interfaces:**
- Produces in `tables.py`:
  - `SOURCE = "https://syntaxscore.org/calculator/syntaxscore/javascript/frameset.js"`, `VERSION = "official calculator 2.28"`
  - `SEGMENT_IDS: tuple[str, ...]` (the 25 ids in the official table order, which is also the order "most proximal" is judged in)
  - `weight(segment: str, dominance: str) -> float | None` (`dominance` is `"right"` or `"left"`; `None` means the segment does not apply to that dominance)
  - `MEDINA: dict[str, tuple[int, int, int, int]]` (letter to (main proximal, main distal, side, points))
  - `OSTIAL_SEGMENTS = {"1", "5", "6", "11"}`
  - `VISUALIZED_HELP: dict[str, tuple[int, int, frozenset[str]]]` (TO main segment to (start index, end index, denied segment ids), indexes into `SEGMENT_IDS`)

- [ ] **Step 1: Write failing tests** with the official values: `weight("5","right") == 5`, `weight("5","left") == 6`, `weight("6","right") == 3.5`, `weight("1","left") == 0`, `weight("4","left") is None`, `weight("16b","left") is None`, `weight("15","right") is None`, `weight("15","left") == 1`, `weight("13","left") == 1.5`, `weight("14a","left") == 1`; `len(SEGMENT_IDS) == 25`; `MEDINA["A"] == (1,0,0,1)` and `MEDINA["D"][3] == 2` for D to G; `VISUALIZED_HELP["5"]` has denied `{"9","9a","10","10a","12","12a","12b","14a","14b"}`; `VISUALIZED_HELP["4"]` has denied `{"4","16"}`; `VISUALIZED_HELP["11"]` has denied `{"12","12a","12b","14a","14b"}`.
- [ ] **Step 2: Run** `python -m pytest tests/scoring/test_tables.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `tables.py`** by transcribing `meDiffuseTableArray` and `meSegmentVisualizedTableHelp` from official `frameset.js` (lines ~958 to ~1025). Port all rows of the help table, including the rows for 14, 14a, 14b, 15 and `none` entries, exactly.
- [ ] **Step 4: Run test.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(scoring): official segment weights and lookup tables`.

---

### Task 2: Model and validation

**Files:**
- Create: `src/cagsyntax/scoring/model.py`, `src/cagsyntax/scoring/validate.py`
- Test: `tests/scoring/test_validate.py`

**Interfaces:**
- Consumes: `weight`, `OSTIAL_SEGMENTS`, `MEDINA`, `VISUALIZED_HELP`, `SEGMENT_IDS`.
- Produces in `model.py` (dataclasses; `None` means "not answered"):
  - `Lesion(segments: list[str], occlusion: bool | None = None, first_segments: list[str] = [], age_over_3_months: str | None = None  # "no"|"yes"|"unknown", blunt_stump: bool | None = None, bridging: bool | None = None, beyond_first_visualized: str | None = None  # segment id or "none", side_branch: str | None = None  # "no"|"small"|"large"|"both", trifurcation: int | None = None  # 0 = no, 1 to 4 = diseased segments, bifurcation: str | None = None  # "none" or "A".."G", bifurcation_angle_lt70: bool | None = None, aorto_ostial: bool | None = None, severe_tortuosity: bool | None = None, length_gt20: bool | None = None, heavy_calcification: bool | None = None, thrombus: bool | None = None)`
  - `Case(dominance: str | None, scoring_dominance: str | None, lesions: list[Lesion], diffuse_segments: list[str])`
  - `Issue(code: str, message: str, lesion: int | None)` (lesion index 0-based or `None`)
  - `Part(label: str, points: float)`, `LesionResult(total: float, parts: list[Part])`, `CaseResult(status: str  # "complete"|"incomplete"|"invalid", issues: list[Issue], total: float | None, group: str | None, scoring_dominance: str | None, dominance: str | None, lesions: list[LesionResult], diffuse_points: float)`
- Produces in `validate.py`: `validate(case: Case) -> tuple[list[Issue], list[Issue]]` returning (errors, missing). Errors make the case `invalid`; missing items make it `incomplete`.

- [ ] **Step 1: Write failing tests**, each asserting the exact issue code:
  - Missing, code `no_dominance`; co-dominant with `scoring_dominance=None` gives `no_scoring_dominance` (Review Focus 4); `scoring_dominance` given when `dominance` is right or left and differs gives error `dominance_mismatch`.
  - Missing, code `no_lesions` for zero lesions (Review Focus 1); missing, code `no_segments` for a lesion with `segments == []` (Review Focus 2).
  - Error `segment_not_applicable` for segment `"15"` under right and `"4"` under left (Review Focus 3); error `unknown_segment` for `"99"`; error `too_many_lesions` for 13 lesions (Review Focus 5); error `duplicate_segment`.
  - Occlusion: error `first_segment_not_in_lesion` when a `first_segments` entry is not in `segments`; error `occlusion_fields_without_occlusion` when `occlusion` is false but any of `first_segments`, `age_over_3_months`, `blunt_stump`, `bridging`, `beyond_first_visualized`, `side_branch` is set; missing `occlusion_incomplete` when `occlusion` is true and `first_segments` is empty or any sub-answer is `None`.
  - Error `length_with_occlusion` when `occlusion` and `length_gt20` is true. Error `trifurcation_and_bifurcation` when `trifurcation > 0` and `bifurcation` is not `"none"`/`None`. Error `angle_without_bifurcation`. Error `ostial_not_applicable` when `aorto_ostial` is true and no segment is in `OSTIAL_SEGMENTS`. Error `diffuse_segment_not_applicable`. Error `beyond_segment_invalid` when `beyond_first_visualized` is neither `"none"` nor inside the range `VISUALIZED_HELP` allows for the occlusion's main segment (the first of `first_segments` in `SEGMENT_IDS` order, minus the denied ids and minus segments not applicable to the dominance).
  - Missing `question_unanswered` for each unanswered question that applies: trifurcation, bifurcation (and angle when bifurcation is a letter), tortuosity, calcification, thrombus, aorto-ostial (only when a segment in `OSTIAL_SEGMENTS` is selected), length (only when no occlusion), occlusion itself.
- [ ] **Step 2: Run** `python -m pytest tests/scoring/test_validate.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement the dataclasses and `validate`.** Validation must not raise for any malformed input (wrong types are reported as errors).
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(scoring): case model and validation`.

---

### Task 3: Engine for non-occluded lesions and all other features

**Files:**
- Create: `src/cagsyntax/scoring/engine.py`
- Test: `tests/scoring/test_engine.py`

**Interfaces:**
- Consumes: Task 1 tables, Task 2 model and `validate`.
- Produces: `score_case(case: Case) -> CaseResult` and `group_for(total: float) -> str`. Rules ported from official `frameset.js`: non-occluded segment weight x2; trifurcation points `n + 2`; bifurcation `MEDINA[letter][3]` plus 1 for angle under 70 degrees; aorto-ostial 1; severe tortuosity 2; length over 20 mm 1; heavy calcification 2; thrombus 1; diffuse disease 1 per segment (whole case, counted in `diffuse_points`, not in any lesion). The result uses `scoring_dominance` (or `dominance` when right or left). `invalid` cases and `incomplete` cases return `total=None`, `group=None`, empty lesion results, and the issues.

- [ ] **Step 1: Write failing tests** (values from the official weights): LAD proximal right = 7.0; LM right = 10.0; LM left = 12.0; RCA mid left = 0.0; LM+6 left with Medina D and angle = (6+3.5)*2+2+1 = 22.0; trifurcation 3 on segment 8 right = 2+5 = 7.0; tortuosity+calcification+thrombus on segment 8 right = 2+2+2+1 = 7.0; length on segment 8 right = 3.0; diffuse segments `["7","8"]` adds 2 to the total and shows `diffuse_points == 2`; co-dominant with `scoring_dominance="left"` uses left weights and echoes both; `group_for(22) == "low"`, `group_for(23) == "intermediate"`, `group_for(32) == "intermediate"`, `group_for(33) == "high"`; incomplete case returns `total is None`; every `LesionResult.parts` points sum equals the lesion total.
- [ ] **Step 2: Run** `python -m pytest tests/scoring/test_engine.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `score_case` and `group_for`.**
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(scoring): score non-occluded lesions and lesion features`.

---

### Task 4: Total occlusion and the beyond-occlusion rule

**Files:**
- Modify: `src/cagsyntax/scoring/engine.py`
- Test: `tests/scoring/test_engine.py`

**Interfaces:**
- Produces: occlusion scoring inside `score_case`. Rules from official `CalculateTotalOcclusion`, `SetAgeOfTO`, `SetBluntStump`, `setBridging`, `setSideBranch`, `setVisualizedByContrast`, `calculateQ4V_TO5`: each lesion segment weight x2, except segments listed in `first_segments` weight x5; age `"yes"` or `"unknown"` 1; blunt stump 1; bridging 1; side branch any value except `"no"` 1; beyond-occlusion points by `visualized_points(case_dominance: str, main_segment: str, first_visualized: str) -> int`, ported exactly from `setVisualizedByContrast` including the in-order special cases (16, 4, `"none"` right-dominance, `"none"` any dominance) and the proximal-segment-5 branch (`calculateQ4V_TO5`). `main_segment` is the first id of `first_segments` in `SEGMENT_IDS` order. The scan starts at the `VISUALIZED_HELP[main]` start index, skips the denied ids and ids not applicable to the dominance, adds 1 per segment before `first_visualized`, starts at -1 and clamps at 0.

- [ ] **Step 1: Write failing tests**: single TO in segment 2 right with `first_segments=["2"]` = 1*5 = 5 plus age yes 1, blunt 1, bridging 1, side branch large 1, beyond none: `visualized_points("right","2","none")` equals the official value (compute by hand from the table: segments 2, 3, 4, 16 present in range 1..4 with denied none, then special case `"none"` number 3 = 1; so count by walking the code, and confirm against the golden file in Task 6); TO with `first_segments=["2","3"]` weights 5 + 5; TO spanning segments 2 and 3 with only 2 first gives 5 + 2; marked-first change does not affect non-TO lesions; proximal 5 with left dominance and `"none"` = 4, right dominance and `"none"` = 3, `"7"` = 1, `"8"` = 2, `"13"` = 1, `"14"` = 2, left `"15"` = 3; TO main 4 under right with denied `{"4","16"}`; `age_over_3_months == "no"` scores 0.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `visualized_points` and the occlusion branch.
- [ ] **Step 4: Run tests.** Expected: PASS (hand-computed values may need correction after Task 6; any correction is a ledgered ruling backed by an oracle number).
- [ ] **Step 5: Commit** `feat(scoring): total occlusion and beyond-occlusion rule`.

---

### Task 5: Official-code oracle

**Files:**
- Create: `tools/oracle/fetch_official.py`, `tools/oracle/driver.mjs`, `tools/oracle/generate_golden.py`
- Modify: `.gitignore` (add `tools/oracle/official/`)
- Output: `tests/scoring/golden.json`

**Interfaces:**
- `fetch_official.py`: downloads the pages and scripts listed in the research (`frameset.js`, `form.js`, `form.htm`, `lesion_segments.htm`) into `tools/oracle/official/`, checks each returned HTTP 200, writes a `VERSION.txt` with the calculator version string and download date. Network is used only here.
- `driver.mjs`: `node tools/oracle/driver.mjs < cases.json > results.json`. It evaluates `frameset.js` with `node:vm` in a fresh context that exposes only stub `document`, `window`, `parent` and `alert` objects (no `require`, `fs`, `process`, network). For each case it resets the official state and replays the official handlers in the order the real forms call them (read `form.js` lines ~80 to ~560 and `lesion_segments.htm` line ~165 for the call order), then returns `{total: GetScore(), perLesion: meScorePerLesion[0..n-1]}`.
- `generate_golden.py`: seeded (`random.Random(20261120)`) generator of at least 400 cases that only use legal UI paths (the same rules as `validate`, so every case is a valid complete `Case`), covering both dominances, 1 to 6 lesions, all 25 segments, every Medina letter, trifurcation 0 to 4, occlusions with every first-segment/visualized combination reachable per `VISUALIZED_HELP`, and diffuse segments. Writes `tests/scoring/golden.json` as a list of `{"case": <Case as dict>, "official": {"total": ..., "per_lesion": [...], "diffuse": ...}}` plus a `meta` object recording the official version and generation date.

- [ ] **Step 1: Write failing test** `tests/scoring/test_oracle_tools.py::test_driver_is_sandboxed_and_scores_a_known_case`: runs `driver.mjs` on one case (proximal LAD, right dominance, no other features) and asserts the official total is 7 and that a hostile script cannot read the filesystem (evaluate a one-line stub that tries `require("fs")` in the same sandbox helper and assert it throws). Skip the test with a clear message if `tools/oracle/official/frameset.js` is absent.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement the three tools**, run `python tools/oracle/fetch_official.py`, then `python tools/oracle/generate_golden.py`.
- [ ] **Step 4: Run** the oracle test. Expected: PASS; confirm `golden.json` has at least 400 cases and contains no case with a `None` total.
- [ ] **Step 5: Commit** `test(scoring): oracle tools and golden official results` (never commit `tools/oracle/official/`).

---

### Task 6: Golden comparison and fixes

**Files:**
- Test: `tests/scoring/test_golden.py`
- Modify: `src/cagsyntax/scoring/engine.py` (only to fix confirmed engine bugs)

**Interfaces:**
- Consumes: `golden.json`, `score_case`.

- [ ] **Step 1: Write the test**: for each golden entry, `score_case(Case.from_dict(entry["case"]))` must have `total == official.total`, each lesion total equal to `official.per_lesion[i]`, and `diffuse_points == official.diffuse`; the failure message prints the case index and both numbers. Add `Case.from_dict` to `model.py` if not present.
- [ ] **Step 2: Run** `python -m pytest tests/scoring/test_golden.py -q`. Expected: some FAIL on first run.
- [ ] **Step 3: For each mismatch decide and record**: engine bug (fix the engine with a hand-written regression test in `test_engine.py` first), or an official-code quirk (a UI path the real forms cannot reach). Quirks excluded from the golden set must be listed in `tests/scoring/KNOWN_OFFICIAL_QUIRKS.md` with the case and the reason; the engine does not copy official bugs.
- [ ] **Step 4: Run the whole suite** `python -m pytest -q`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat(scoring): engine matches official calculator on golden cases`.

---

### Task 7: Spec and documentation update

**Files:**
- Modify: `docs/specs/2026-11-20-cag-syntax-ai-design.md`, create `src/cagsyntax/scoring/README.md`

- [ ] **Step 1: Update spec section 5.2** with: the co-dominance decision, the source and version constant, and the oracle verification method with the number of golden cases and the quirks file.
- [ ] **Step 2: Write `scoring/README.md`**: how to call `score_case`, what `invalid`/`incomplete`/`complete` mean, how to regenerate the golden file (`fetch_official.py`, `generate_golden.py`), and the licensing note that official code is never committed.
- [ ] **Step 3: Run** `python -m pytest -q`. Expected: all PASS.
- [ ] **Step 4: Commit** `docs: record scoring engine decisions and verification`.

---

## Self-Review

- **Spec coverage:** 5.2 inputs (Tasks 1, 2), outputs and groups (Task 3), official-tables provenance (Task 1, 7), impossible combinations and incomplete cases (Task 2), engine purity (architecture), section 8 "must match official examples" (Tasks 5, 6). Out of scope for this plan: scoring form, case store, SYNTAX II (spec steps 3 and later).
- **Differences from the step-1 web prototype:** the beyond-occlusion rule is now the official table, not a simple count; multiple first segments are allowed; segments not applicable to the dominance are errors, not silently dropped.
- **Type consistency:** `Lesion`, `Case`, `Issue`, `Part`, `LesionResult`, `CaseResult` are defined in Task 2 and used unchanged in Tasks 3, 4 and 6; `weight`, `SEGMENT_IDS`, `VISUALIZED_HELP`, `MEDINA`, `OSTIAL_SEGMENTS` are defined in Task 1.
- **Open risks:** Task 4's hand-computed expected values may be wrong until checked against the oracle (called out in its Step 4); official bifurcation re-selection and `meAortoOstialLesion==-1` code bugs are UI-state bugs the driver must avoid by setting each answer once; the 2005 paper was not consulted, so weights are verified against the official calculator, not the paper.
