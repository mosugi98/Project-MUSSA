# Step 0: the shared data contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** One Pydantic v2 schema, `cagsyntax.contract`, that every stage (vision output, reconciliation, the SYNTAX engine, the viewer and review) reads and writes, so findings stay traceable to series, frame, C-arm angles and a box, and the AI's raw prediction is stored next to the physician's final answer.

**Architecture:** Additive package `src/cagsyntax/contract/` (`models.py`, `adapters.py`, `schema.py`). The SYNTAX engine in `scoring/` stays the only place a score is computed: the contract's `ScoreSummary` is a read-only snapshot made from the engine's `CaseResult`, and scoring always goes `CaseForm -> Case -> score_case`. Adapters convert to and from the existing dataclasses (`Lesion`, `Case`, `CaseResult`, `Suggestion`) without changing them. A JSON Schema file is checked in and a test fails if it drifts from the models.

**Tech Stack:** Python 3.11+, pydantic >= 2.5. No Qt in the contract package.

**Spec:** `docs/specs/2026-11-20-cag-syntax-ai-design.md`; roadmap decisions of 2026-11-22: same-program viewer (no network bridge), 25 sub-segments kept, LLM optional and later.

## Global Constraints

- Segment names are exactly the 25 in `ai.segment_names.SEGMENT_NAMES`; AHA 16 groups are a derived view, not stored.
- Models reject unknown fields (`extra="forbid"`) and unknown enum strings; a bad file fails with a plain message, never a traceback.
- Every `Evidence` names a series that exists in the analysis, and a frame inside that series.
- `physician_final_approved` requires a reviewer; the AI's raw prediction is never overwritten.
- No patient identifiers anywhere in the contract (series/study UIDs are the de-identified ones, reviewers are store ids).
- Timestamps are timezone-aware.

## Review Focus

- A lesion form with `None` answers (draft) must validate: an incomplete form is normal, not an error.
- Round trip `Case -> CaseForm -> JSON -> CaseForm -> Case` must score identically for every lesion type.
- A schema file edited by hand or a model edited without regenerating the schema is caught by a test.
- A document from a newer schema version is refused with a message naming both versions.
- Evidence pointing at a missing series or a frame past the end is rejected.

---

### Task 1: Models and validation

**Files:** Create `src/cagsyntax/contract/__init__.py`, `models.py`; Test `tests/contract/test_models.py`.

**Interfaces:** `SCHEMA_VERSION = "1.0"`; `ModelRef(name, identity)`, `Evidence(series_uid, frame, primary_angle, secondary_angle, box)`, `Finding(evidence, segment, score, pixels, overlap, models)`, `LesionForm` (all `Lesion` fields), `CaseForm(dominance, scoring_dominance, lesions, diffuse_segments)`, `LesionProposal(form, findings, source)`, `Review(ai_raw_prediction, physician_final_approved, reviewer_id, reviewer_level, reviewed_at)`, `ScoreSummary(status, total, group, engine_version, issues, lesion_totals, diffuse_points)`, `SeriesInfo(...)`, `CaseAnalysis(schema_version, study_uid, series, findings, proposals, review, score, created_at)`.

- [ ] Tests for every validation rule above (RED), then models (GREEN).

### Task 2: Adapters

**Files:** Create `contract/adapters.py`; Test `tests/contract/test_adapters.py`.

**Interfaces:** `lesion_to_form`, `form_to_lesion`, `case_to_form`, `form_to_case`, `score_to_summary(CaseResult)`, `finding_from_suggestion(suggestion, series_uid, frame, primary_angle, secondary_angle, models)`, `proposals_from_findings(findings) -> list[LesionProposal]`.

- [ ] Round-trip tests with the engine's own builders and identical scores; suggestion mapping; proposals only for placed segments.

### Task 3: Serialisation and schema

**Files:** Create `contract/schema.py`, `tools/contract/export_schema.py`, `docs/contract/cag-analysis.schema.json`; Test `tests/contract/test_schema.py`.

**Interfaces:** `to_json(analysis) -> str`, `from_json(text) -> CaseAnalysis` (raises `ContractError`), `json_schema() -> dict`.

- [ ] Tests: JSON round trip, version refusal, plain-language errors, checked-in schema equals generated.
- [ ] Add `pydantic>=2.5` to `pyproject.toml`; full suite; commit.
