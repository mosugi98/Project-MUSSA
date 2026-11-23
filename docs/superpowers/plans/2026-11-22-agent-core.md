# Agentic SYNTAX core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Give MUSSA an agent layer that turns what the vision models see in each angiographic run into proposed lesions with full evidence (series, frame, angles, box), lets the scorer review and edit them with the score recalculating live, and jumps the viewer to the exact series and frame of any lesion. The SYNTAX score is only ever computed by the project's verified engine.

**Architecture:** New package `src/cagsyntax/agent/`, in-process (no network API). Types use the names of the supplied draft (`StudySyntaxInput`, `StudySyntaxOutput`, `LesionInput`, `ViewEvidence`, `RawCVLesionCandidate`, `RunPerceptionSummary`) but are thin layers over `cagsyntax.contract` and `cagsyntax.scoring`: `score_study()` converts to the engine's `Case`, calls `score_case`, and converts back. Reconciliation across views is deterministic first; an LLM node is an optional, off-by-default plug-in behind an interface (later). The supplied `syntax_engine.py` and `orchestrator.py` are kept as reference under `docs/reference/agentic-draft/` and are not imported.

**Tech Stack:** pydantic >= 2.5; existing onnxruntime models; PySide6 (viewer wiring). No langchain/langgraph/openai dependency in this plan.

**Spec:** `docs/specs/2026-11-20-cag-syntax-ai-design.md`; decisions of 2026-11-22: same-program viewer, 25 sub-segments, LLM optional and later, project engine stays the only scoring authority, unmeasured values optional.

## Global Constraints

- Only `scoring.score_case` computes a score. No second engine.
- Unmeasured values (QCA %, vessel diameter, lesion length, morphology hints, SNR, C-arm angles) are `None`, never defaulted to a number; an unanswered question stays unanswered so the engine reports "incomplete".
- Official rules win over the draft: only the first segment of an occlusion counts x5 (others x2); points for segments beyond an occlusion come from the first visualized segment, not a typed count; answers that do not apply (for example aorto-ostial at segment 8) are reported by the engine as invalid, never silently scored.
- Boxes are integer pixel `xyxy`, x1/y1 exclusive, in the frame's own size (the contract's convention); ARCADE categories are matched by name.
- Every proposed lesion cites evidence; nothing is auto-confirmed.

## Review Focus

- A draft (AI-proposed) lesion must stay incomplete until the scorer answers; its total must be `None`, never 0.
- Two occluded segments flagged in one lesion are refused with an explanation, not scored x5 twice.
- A multi-view study never loses a significant candidate silently (reconciliation reports what it merged and what it left unplaced).
- Physician edits re-run the same engine path as the form (one source of truth for live recalculation).

---

### Slice 1 (this turn): housekeeping, types, adapters, ported tests

- [ ] Move the three supplied root files to `docs/reference/agentic-draft/` with a README saying they are reference only.
- [ ] `agent/schema.py`: `ViewEvidence`, `InvolvedSegment`, `TotalOcclusionDetails`, `BifurcationDetails`, `TrifurcationDetails`, `LesionInput` (with `draft`), `StudySyntaxInput`, `LesionBreakdown`, `StudySyntaxOutput`, `RawCVLesionCandidate`, `RunPerceptionSummary`.
- [ ] `agent/adapters.py`: `lesion_input_to_lesion`, `study_to_case`, `score_study`, `AdapterError`.
- [ ] Tests: the draft's three scenarios reproduced against the real engine (13.0, 29.5, 14.0), the invalid-combination guardrail, the documented differences, draft lesions, evidence flags.

### Slice 2: perception wiring
`agent/perception.py`: `perceive_series(path, segmenter, stenosis, frames=...) -> RunPerceptionSummary` using `read_xa`, `Segmenter.predict`, `StenosisFinder.candidates` and `suggest`.

### Slice 3: deterministic reconciliation
`agent/reconcile.py`: group candidates across runs by segment and angle, pick the primary view, list supporting views and `needs_attention`, output `StudySyntaxInput` with draft lesions.

### Slice 4: viewer wiring and storage
Run-AI-on-study action, a proposals list that jumps to series and frame, live recalculation through `score_study`, AI-raw versus physician-final in the store (schema v3).

**Done (commits 66c6262, 0c7f6c2, cea662d, 19a3f7b).** Rulings made while building it:
- Live recalculation needed no new code: the scoring panel already recalculates through the engine on every edit, and the AI only adds segment-only lesions to that form. `score_study` stays the adapter for code that holds a `StudySyntaxInput`.
- AI-raw versus physician-final: new store table `ai_runs` (schema v3, automatic `.v2.bak` backup) keeps the raw runs and reconciliation as JSON, the proposed lesion ids and the ones the scorer took, with the model files. The scorer's own answer stays the `entries` row. Conversion to the contract's `Review`/`CaseAnalysis` is not done: nothing reads the contract yet, so it would be unused code.
- The dialog is modal, with a "Show in viewer" button that jumps the main window to the series and frame (`CineWidget.show_frame`). The box is not drawn on the frame yet.
- Cancelling records nothing; an empty result and "ticked none" are recorded (they are findings about the model).
- Only the series of the open case are analysed, so one patient's findings cannot reach another's form (tested with a second study in the library).

### Slice 5 (optional, off by default)
An LLM reconciliation node behind the `Reconciler` interface.
