# MUSSA changelog

MUSSA is educational decision-support software for SYNTAX scoring. It is not a certified medical device, and no
AI output in it is a diagnosis.

## Unreleased (branch agent-core)

### New
- **Coronary artery diagram.** The scoring panel has a realistic heart illustration beside the stick-figure tree
  (switch: Diagram | Schematic). All 25 segments are clickable on it. Segments that are hidden from the front view
  (circumflex system, posterior descending, posterolateral, left main) are drawn dashed because their position is
  schematic. The illustration is by DBCLS, CC BY 4.0, modified. If its image file is missing, the panel uses the
  Schematic.
- **Run AI on study.** One click runs both models over every series of the open case, merges what they saw into one
  proposed lesion per segment (best view, supporting views, and plain-language reasons to check it) and lets the
  scorer tick the ones they agree with. A "Show in viewer" button jumps to the exact series and frame. Only the
  segment is filled in; dominance and every answer stay the scorer's. Needs the segment and stenosis models.
- **Case store schema 3.** The AI's raw proposal for a study is kept (`ai_runs`) beside the scorer's own answer, with
  which lesions were taken and the model files. An older store is upgraded automatically and a `.v2.bak` copy is kept.
- Agent layer under `cagsyntax.agent` (typed perception, deterministic reconciliation, adapters to the verified
  SYNTAX engine). Not yet used for key-frame choice, QCA, vessel diameter or foreshortening.

## 2.0.0 - 2026-11-22

The second major version. It adds AI suggestions the scorer can accept or reject, a new look, a shared data
contract, and tools to label your own cases and train better models. The window title now shows "MUSSA 2.0".

**Git tags.** `v1.0-checkpoint` marks the code as it was just before the data contract was merged (everything below
except the contract). `v2.0.0` marks this release.

### New
- **Suggest lesions.** A stenosis model finds narrowings, the segment model places each one in a segment, and the
  scorer ticks the ones they agree with. Only the segment is filled in; nothing is pre-ticked, scored or confirmed by
  the AI. Every accept and reject is logged with the frame and the model files. It refuses when the series on screen
  belongs to another case, when the scoring panel is hidden, or while the cine is playing.
- **Shared data contract** (`cagsyntax.contract`, Pydantic v2). One schema for findings (with series, frame, C-arm
  angles, box and model identity), the scoring form, lesion proposals, review (the AI's raw prediction stored next to
  the physician's approved answer) and the engine's score. Strict validation, plain-language errors, adapters to and
  from the engine's own types, and a checked-in JSON Schema (`docs/contract/cag-analysis.schema.json`). Nothing in
  the app uses it yet; it is the base for the next steps.
- **New design.** Green and yellow, glossy and rounded, with smooth hover and press animation, and an **Appearance**
  window to change colours, roundness, gloss, animation speed and text size (kept in `theme.json`).
- **Labelling toolkit** (`tools/labelling/`): export de-identified frames for labelling (skipping series that may have
  burned-in patient text), a ready CVAT label list, a plain-words label checker, and a study-safe train/val split.
- **Better training.** A loss that no longer lets the model collapse to empty masks, rare-segment oversampling, early
  stopping, fine-tuning from earlier weights, your own validation folders, and a stenosis task. One Colab notebook
  trains both models. See `docs/labelling-and-training-guide.md`.
- **Portable Windows build** (`tools/packaging/build_exe.py`): a folder with `MUSSA.exe` that needs no Python, with a
  built-in `--selftest`.
- **Per-segment thresholds** for the segment model in its model card, and `tools/ai/tune_thresholds.py`.

### Changed
- The case store is now schema version 2 (adds the suggestion log). A version 1 store is backed up to
  `cases.sqlite.v1.bak` and upgraded in place; nothing is lost. A store written by this version cannot be opened by an
  older MUSSA.
- Model identity in logs is the training date plus a short hash of the model file.
- `pydantic` is a declared dependency.

### Known limits
- The AI models are research-grade and measured on public ARCADE data only. The segment model's last measured test
  Dice was 0.46; the stenosis model must still be trained (guide above).
- Diameter and stenosis percentage, lesion morphology, dominance and multi-view reconciliation are not automated.
  They stay with the scorer.

## 1.0 - the first complete version

DICOM XA import and viewer, the SYNTAX Score I engine (official calculator 2.28, checked against the official code),
the scoring form and case store, dataset export, and the segment overlay.
