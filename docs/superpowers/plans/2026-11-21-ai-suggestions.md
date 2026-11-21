# AI suggestions (stenosis candidates, form suggestions, better segment training) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** MUSSA suggests where the stenoses are and which segments they lie in, the scorer accepts or rejects each suggestion, every decision is logged, and the segment model trains better. The score itself is still entered, completed and confirmed by people.

**Architecture:** Two separate ONNX models run on the same frame. The existing segment model (25 channels) says where each SYNTAX segment is. A new stenosis model (1 channel, trained on ARCADE `stenosis`, 1000/200/300 images) says where narrowings are. Overlapping the two gives "stenosis in segment N". Suggestions become segments-only draft lesions that the scorer adds explicitly. A `suggestion_events` table records every accept and reject with the model versions, for later learning.

**Tech Stack:** PySide6, onnxruntime, numpy, Pillow, SQLite; PyTorch + segmentation-models-pytorch only in the cloud training script.

**Spec:** `docs/specs/2026-11-20-cag-syntax-ai-design.md` (AI helper section: suggestions only, never a diagnosis, scorer decides).

## Global Constraints

- AI output is always labelled "AI suggestion - not a diagnosis". Nothing is pre-ticked; nothing is confirmed or scored by the AI.
- Suggestions fill only `Lesion.segments`. Dominance and every clinical-judgement answer stay unanswered for the scorer.
- Models are optional: no model file means the feature is off with a clear message, never a crash.
- The training script stays PyTorch-only-in-the-cloud; the app and tests need only onnxruntime/onnx.
- Existing stores (schema v1) must open and be migrated without losing data.
- Tests first for every task; full suite green before each commit.

## Review Focus

- A stenosis candidate that overlaps no segment, or several segments equally: reported as "unplaced" / lowest-numbered tie-break, never dropped silently.
- Empty frame / no candidates: a clear "nothing found" message, no empty dialog.
- Wrong or missing stenosis model card: feature unavailable with the reason, segment overlay unaffected.
- Applying a suggestion for a segment that is not valid for the chosen dominance (e.g. 16a with no dominance): handled by the existing form rules, not crashing.
- Logging fails (store locked): the suggestion still applies, the failure is shown, nothing is lost silently.

---

### Task 1: Better segment training

**Files:** Modify `tools/training/train_segmentation.py`; Create `src/cagsyntax/ai/sampling.py`; Test `tests/ai/test_sampling.py`, extend `tests/ai/test_training_kit.py`.

**Interfaces:** Produces `rare_segment_weights(counts: list[dict[str, int]], power: float = 0.5) -> list[float]` (one weight per image; images containing rare segments weigh more, images with none get the base weight 1.0 relative scale), and CLI options `--oversample-rare` (default on, power 0.5), `--init-weights PATH` (start from a previous `segments_best.pt`), `--extra-train PATH` (repeatable, additional COCO split folders, e.g. your own labelled cases).

- [ ] Test: an image holding the rarest segment gets a larger weight than one holding only the commonest; empty image gets the base weight; weights positive and finite; `power=0` gives equal weights.
- [ ] Implement `sampling.py` (pure numpy); copy into the kit (`make_kit.py` SHARED list, byte-identical test updated).
- [ ] Use a `WeightedRandomSampler` in `train()` when `--oversample-rare`; support `--init-weights` and `--extra-train` (concatenate datasets). Parser test for the three options.
- [ ] Smoke run (`--smoke`) still passes in the torch scratch environment.

### Task 2: Stenosis data and training

**Files:** Modify `src/cagsyntax/ai/arcade.py` (new `mode`), `tools/training/train_segmentation.py` (`--task`); Test `tests/ai/test_arcade.py`, `tests/ai/test_training_kit.py`.

**Interfaces:** `ArcadeSplit(root, mode="segments"|"stenosis")`; in stenosis mode `load_masks(i)` returns bool `(1, H, W)` from the `stenosis` category; segment mode unchanged. `--task segments|stenosis` (stenosis: 1 class named `stenosis`, output `stenosis.onnx` + `stenosis.card.json`, metrics per the single class).

- [ ] Tests for stenosis-mode masks (several polygons OR-ed, other categories ignored, image without stenosis gives an empty mask).
- [ ] Implement; `SEGMENT_NAMES`-based class list becomes a `task`-dependent list in training; card `classes` is `["stenosis"]`.
- [ ] Parser and smoke test for `--task stenosis`.

### Task 3: Stenosis finder (inference)

**Files:** Create `src/cagsyntax/ai/stenosis.py`; Test `tests/ai/test_stenosis.py` (toy ONNX models from `tests/ai/toy_models.py`, extended with a 1-channel option).

**Interfaces:** `StenosisFinder.load(path) -> StenosisFinder` (same validation style as `Segmenter`, raises `ModelUnavailable`); `.candidates(frame, threshold=None, min_pixels=30) -> list[Candidate]`; `Candidate(mask: np.ndarray[bool], box: tuple[int,int,int,int], pixels: int, score: float)` where score is the mean probability inside the component; components found by 8-connected labelling; sorted by score descending.

- [ ] Tests: loads/refuses (missing, wrong classes, wrong shape), two separate blobs give two candidates with right boxes, tiny blobs under `min_pixels` dropped, card threshold used, input untouched.
- [ ] Implement.

### Task 4: Suggestion engine

**Files:** Create `src/cagsyntax/ai/suggest.py`; Test `tests/ai/test_suggest.py`.

**Interfaces:** `Suggestion(segment: str | None, score: float, pixels: int, overlap: float, box: tuple)`; `suggest(candidates, segment_masks, min_overlap=0.2) -> list[Suggestion]` (segment is the one covering most of the candidate; below `min_overlap` the segment is `None` = unplaced; ties go to the first in `SEGMENT_NAMES` order); `lesions_from(suggestions) -> list[Lesion]` (one lesion per distinct placed segment, only `segments` set).

- [ ] Tests: overlap choice, tie-break, unplaced, duplicates merged keeping the best score, `lesions_from` skips unplaced and sets nothing but segments.
- [ ] Implement.

### Task 5: Suggestion log in the store

**Files:** Modify `src/cagsyntax/store.py` (`SCHEMA_VERSION` 2, migration, `log_suggestions`, `suggestion_events`); Test `tests/test_store_suggestions.py`.

**Interfaces:** `CaseStore.log_suggestions(study_uid, user_id, events: list[SuggestionEvent])` with `SuggestionEvent(series_uid, frame, segment, score, action: "accepted"|"rejected", segment_model: str, stenosis_model: str)`; `CaseStore.suggestion_events(study_uid) -> list[...]`.

- [ ] Tests: v1 database migrates and keeps data; new database has the table; unknown action refused; events round-trip; a locked/failed write raises `StoreError`.
- [ ] Implement.

### Task 6: Suggest lesions in the app

**Files:** Create `src/cagsyntax/ui/suggest_dialog.py`; Modify `src/cagsyntax/app.py`; Test `tests/ui/test_suggest_dialog.py`, `tests/test_suggest_app.py`.

**Interfaces:** `MainWindow.stenosis` (finder or None), `MainWindow.suggest_lesions() -> list[Suggestion] | None`, `SuggestDialog(suggestions, parent)` with `chosen() -> list[Suggestion]`; a toolbar action "Suggest lesions" in the scoring toolbar.

- [ ] Tests: no case open / no model → clear message; nothing found → message, no dialog; dialog lists candidates unticked; applying ticked ones adds lesions with segments only to the form, marks the form as unsaved, logs accepted and rejected events; logging failure is shown but the lesions still apply.
- [ ] Implement; load the finder at start like the segmenter (`models/stenosis.onnx`).

### Task 7: Guides, kit, notebook

**Files:** Create `docs/labelling-and-training-guide.md`; Modify `docs/ai-training.md`, `tools/training/MUSSA_ARCADE_segments.ipynb` (train both models), `docs/user-guide.md`, rebuild the kit; Test `tests/ai/test_training_kit.py` (kit contents).

- [ ] Write the step-by-step guide: labelling your own angiograms (export from MUSSA, label in CVAT, COCO export, check with a MUSSA tool, fine-tune), then training both models on Colab.
- [ ] A checker `tools/ai/check_labels.py` that validates a labelled COCO folder before training (categories, polygons, empty images) and reports problems in plain words; tests first.
- [ ] Notebook trains segments then stenosis and offers four files for download.

### Task 8: Review and merge

- [ ] Final whole-branch review by a fresh most-capable reviewer; one fix pass with RED to GREEN tests; ledger of rulings and deferred minors; full suite; portable build self-test; merge after your say-so.
