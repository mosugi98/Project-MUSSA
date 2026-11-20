# AI Segment Helper (Step 5a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The first AI helper of spec Phase B: a model trained on the public ARCADE `syntax` data outlines the 25 SYNTAX coronary segments on the frame being viewed, shown as a clearly labelled "AI suggestion" overlay; plus the tools to train it on a free cloud GPU and to measure how good it is.

**Architecture:** A Qt-free `cagsyntax.ai` package holds the ARCADE loader (COCO polygons to 25 masks), one shared preprocessing function, accuracy metrics and an ONNX inference wrapper. A self-contained training kit (`tools/training/`) trains a multi-label U-Net on ARCADE in a cloud notebook and exports an ONNX model plus a model card. The app loads `MUSSA-data/models/segments.onnx` if present and offers an overlay toggle on the viewer; without a model the app works exactly as before.

**Tech Stack:** Python 3.13, numpy, Pillow, onnxruntime (new, runtime), onnx (new, tests only), PySide6; PyTorch and segmentation_models_pytorch only inside the cloud training kit (never imported by the app).

**Spec:** `docs/specs/2026-11-20-cag-syntax-ai-design.md` (sections 2, 6, 7, 8). Not in this plan (planned after the review stop): the stenosis helper, pre-filling the form from suggestions, and logging accepts and edits.

## Global Constraints

- The AI only suggests. It never changes the scoring engine (spec 6). In this slice it does not touch the scoring form at all.
- Suggestions appear as overlays marked as AI-suggested (spec 6).
- Start from a model trained on public coronary angiography data; check dataset licensing and fit before use (spec 6). ARCADE: CC0, `https://zenodo.org/records/10390295`, DOI 10.5281/zenodo.10390295, `arcade.zip` 451.6 MB, md5 `c5b1973ade06f7dff210f878161e1a76`; its page states no ethics, consent or de-identification statement, and says its dataset article "will be provided later".
- No cloud processing of patient data; patient images stay on the hospital machine (spec 2). Only ARCADE (public) is used in the cloud. Nothing from the hospital store or case store goes into the training kit.
- Runs fully offline on the PC after the model file is installed (spec 4).
- Labeled as decision support for research and teaching, not a certified medical device (spec 7).
- Evaluation: compare to the reference on held-out data (spec 6); here: per-segment overlap on the ARCADE test split.
- Segments are the full 25 sub-segments (spec 5.2): 1, 2, 3, 4, 5, 6, 7, 8, 9, 9a, 10, 10a, 11, 12, 12a, 12b, 13, 14, 14a, 14b, 15, 16, 16a, 16b, 16c.

## Decisions (my calls, for review)

- **One helper per slice:** this plan is segment outlining only. Stenosis candidates and form suggestions follow in a second plan.
- **Training place:** a free cloud GPU notebook trains on ARCADE only (the user's choice). The app never trains. Fine-tuning on the user's confirmed cases is out of this plan and would stay local.
- **Model:** multi-label U-Net, ResNet-34 encoder (ImageNet weights downloaded by the notebook), 25 sigmoid outputs (segments can overlap), input 512 x 512 (ARCADE's native size), BCE + Dice loss. No horizontal or vertical flips (anatomy is orientation-specific); only brightness, contrast, gamma, small shifts, scale and rotation.
- **Splits:** ARCADE's own train (1000), val (200) and test (300) from the `syntax` folder. The test split is touched only by the final evaluation.
- **One preprocessing function** (`ai/preprocess.py`) is the single source: the training kit gets a copy of that file, so training, evaluation and the app cannot drift apart.
- **Where the model lives:** `MUSSA-data/models/segments.onnx` with `segments.card.json` (training data, date, input size, class list, validation and test scores, licence note). The app refuses a model whose class list or input shape does not match.
- **Inference:** on demand for the displayed frame (onnxruntime, CPU), cached per series and frame, with the wait cursor. It is never run automatically in the background.
- **Overlay:** coloured, semi-transparent masks with the segment number at each centroid and a fixed "AI suggestion - not a diagnosis" label; a toggle button on the viewer, off by default.
- **ARCADE stays out of git** (`arcade/` is ignored); the notebook downloads it from Zenodo and verifies the md5.

## Review Focus

1. Without a model file, or with a corrupt or incompatible one, the viewer must work unchanged and say clearly why the overlay is unavailable. Test in Tasks 4 and 6.
2. A model whose output has the wrong number of classes or an unexpected shape must be rejected with a message, never drawn as a wrong overlay. Test in Task 4.
3. The overlay must be labelled as an AI suggestion and must never change scores, forms or stored data. Test in Task 6.
4. Polygon rasterisation must be correct (x, y order, several polygons, polygons touching the border, malformed polygons) and the class names must match our 25 segments, with the `stenosis` class excluded. Tests in Task 1, including the real ARCADE files when present.
5. Preprocessing must be identical in training, evaluation and the app. Test in Tasks 2 and 3.

---

## File Structure

```
src/cagsyntax/ai/__init__.py
src/cagsyntax/ai/arcade.py        # COCO polygons -> masks, ArcadeSplit loader
src/cagsyntax/ai/preprocess.py    # preprocess(frame) -> model input (single source of truth)
src/cagsyntax/ai/metrics.py       # dice/iou per segment and macro averages
src/cagsyntax/ai/segmenter.py     # Segmenter (ONNX), ModelCard, errors
src/cagsyntax/ai/evaluate.py      # evaluate_model(...) -> EvalReport
src/cagsyntax/ai/overlay.py       # masks -> RGBA overlay image (numpy)
src/cagsyntax/viewer/widget.py    # modified: overlay support
src/cagsyntax/app.py              # modified: model loading, AI segments toggle
tools/training/train_segmentation.py   # runs in the cloud notebook (PyTorch)
tools/training/make_kit.py             # builds mussa-training-kit.zip (code + preprocess copy)
tools/training/MUSSA_ARCADE_segments.ipynb
tools/ai/evaluate_segmentation.py      # command line evaluation on ARCADE test
docs/ai-training.md
tests/ai/test_arcade.py, test_preprocess.py, test_metrics.py, test_segmenter.py,
tests/ai/test_evaluate.py, test_overlay.py, test_training_kit.py, tests/test_ai_app.py
```

---

### Task 1: ARCADE loader

**Files:**
- Create: `src/cagsyntax/ai/__init__.py`, `src/cagsyntax/ai/arcade.py`
- Test: `tests/ai/test_arcade.py`

**Interfaces:**
- Produces: `SEGMENT_NAMES: tuple[str, ...]` (the 25 ids in `cagsyntax.scoring.tables.SEGMENT_IDS` order); `polygon_to_mask(polygon: list[float], height: int, width: int) -> np.ndarray` (bool, polygon is the COCO flat list `[x1, y1, x2, y2, ...]`; fewer than 3 points gives an empty mask; points outside the image are clipped); `class ArcadeSplit(root: Path)` where `root` is a split folder such as `arcade/arcade/syntax/train`, with `len(self)`, `image_ids: list[int]`, `load_image(i: int) -> np.ndarray` (uint8, shape H x W, grayscale) and `load_masks(i: int) -> np.ndarray` (bool, shape `(25, H, W)`, channel order `SEGMENT_NAMES`, one channel per segment, several polygons of one segment OR-ed, the `stenosis` category ignored), and `ArcadeSplit.class_counts() -> dict[str, int]` (annotations per segment name). Unknown category names raise `ValueError` at load.

- [ ] **Step 1: Write failing tests** with a tiny synthetic COCO folder built in `tmp_path` (two 64 x 64 PNG images; image 1 with segment `"5"` as the square (10,10)-(30,30), segment `"6"` as two separate polygons, and a `stenosis` annotation; image 2 with a polygon touching the border): `polygon_to_mask` of the square has the expected area (within 2 pixels of 400) and `mask[y, x]` is true at (row 20, column 20) and false at (row 20, column 40), proving x/y order with a non-square rectangle (columns 5..45, rows 10..20: true at row 15, column 40; false at row 40, column 15); fewer than 3 points gives an empty mask; points beyond the image are clipped without error; channels follow `SEGMENT_NAMES` (channel of `"9a"` is index 9); two polygons of `"6"` are OR-ed; the `stenosis` annotation sets no channel; an unknown category raises `ValueError`; `class_counts` counts; `len` and `image_ids` match the JSON. If `arcade/arcade/syntax/train` exists, also check on the real data: every category name is in `SEGMENT_NAMES` plus `"stenosis"`, image 922 loads as 512 x 512 uint8, and its masks have at least 2 non-empty channels (skip the test with a message when the folder is absent).
- [ ] **Step 2: Run** `python -m pytest tests/ai/test_arcade.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `polygon_to_mask` with `PIL.ImageDraw.Draw(...).polygon` and `ArcadeSplit`.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(ai): ARCADE loader with polygon rasterisation`.

---

### Task 2: Preprocessing and metrics

**Files:**
- Create: `src/cagsyntax/ai/preprocess.py`, `src/cagsyntax/ai/metrics.py`
- Test: `tests/ai/test_preprocess.py`, `tests/ai/test_metrics.py`

**Interfaces:**
- Produces in `preprocess.py` (numpy only, no other imports from the project, so it can be copied verbatim into the training kit): `INPUT_SIZE = 512`, `preprocess(frame: np.ndarray) -> np.ndarray` returning float32 of shape `(1, 512, 512)`: accepts uint8 or uint16 2-D arrays of any size, scales to 0..1 by the frame's own min and max (a constant frame gives zeros), resizes to 512 x 512 with bilinear interpolation (PIL), then standardises with mean 0.5 and std 0.5 to the range -1..1; and `resize_mask(mask: np.ndarray, height: int, width: int) -> np.ndarray` (bool, nearest neighbour) for mapping a 512 x 512 prediction back to the frame size.
- Produces in `metrics.py`: `dice(pred: np.ndarray, truth: np.ndarray) -> float | None` and `iou(pred, truth) -> float | None` for boolean masks of equal shape (`None` when both are empty, meaning "segment absent and not predicted", so it is excluded from averages); `per_segment_scores(preds: np.ndarray, truths: np.ndarray) -> dict[str, dict]` for arrays of shape `(25, H, W)` returning, per name in `SEGMENT_NAMES`, `dice`, `iou`, `truth_pixels`, `pred_pixels`.

- [ ] **Step 1: Write failing tests**: output dtype and shape for a 100 x 80 uint8 frame, a 512 x 512 frame and a uint16 frame; value range exactly -1..1 for a gradient frame (min -1.0, max 1.0); a constant frame gives all zeros without a warning; a frame with a bright border gives the same result after multiplying all pixel values by 2 (scale invariance); `resize_mask` keeps boolean dtype and maps a half-image mask to a half-image mask; the preprocessing file imports only `numpy` and `PIL` (read the source and assert no `cagsyntax` import); `dice` of identical masks is 1.0, of disjoint masks 0.0, of half-overlapping equal masks 0.5, and `None` when both are empty; `iou` for the half-overlap case is 1/3; a predicted-only mask gives dice 0.0 (not `None`); `per_segment_scores` returns 25 entries in order with the pixel counts.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement both modules.**
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(ai): shared preprocessing and segmentation metrics`.

---

### Task 3: Training kit

**Files:**
- Create: `tools/training/train_segmentation.py`, `tools/training/make_kit.py`, `tools/training/MUSSA_ARCADE_segments.ipynb`
- Test: `tests/ai/test_training_kit.py`

**Interfaces:**
- Consumes: `ai/arcade.py`, `ai/preprocess.py`, `ai/metrics.py` (copied into the kit).
- Produces: `make_kit.py` with `build_kit(out_zip: Path) -> list[str]` writing a zip that contains `train_segmentation.py`, copies of `arcade.py`, `preprocess.py`, `metrics.py` placed so that `from mussa_ai import arcade, preprocess, metrics` works (a package folder `mussa_ai/`), `segment_names.json` and a `README.txt`; it must contain no file from the app's data folders. `train_segmentation.py` command line: `--arcade <folder holding syntax/ and stenosis/> --out <folder> [--epochs 30 --batch-size 8 --lr 3e-4 --size 512 --encoder resnet34 --smoke]`. It trains on `syntax/train`, selects the best epoch on `syntax/val` by mean Dice, evaluates once on `syntax/test`, exports `segments.onnx` (opset 17, input `image` of shape `[N, 1, size, size]`, output `masks` of shape `[N, 25, size, size]` holding logits, dynamic batch) and writes `segments.card.json` with keys `format_version`, `trained_on` ("ARCADE syntax, https://zenodo.org/records/10390295, CC0"), `trained_at`, `input_size`, `classes` (the 25 names), `preprocess` ("ai/preprocess.py v1: per-frame min-max, resize, mean 0.5 std 0.5"), `val_mean_dice`, `test_mean_dice`, `per_segment_test_dice`, `training` (epochs, batch size, lr, encoder, seed 20261121) and `notice`. `--smoke` trains one epoch on 8 images at size 128 and skips the test evaluation. The notebook cells: install `segmentation-models-pytorch`, download `arcade.zip` from the Zenodo URL and verify the md5, upload and unzip the kit, run the script with a GPU, download `segments.onnx` and `segments.card.json`.

- [ ] **Step 1: Write failing tests** (no PyTorch needed): `build_kit` returns the file list and the zip holds exactly the expected files; `mussa_ai/preprocess.py` inside the zip is byte-identical to `src/cagsyntax/ai/preprocess.py` (Review Focus 5); the kit contains no path under `data`, `store`, `cases.sqlite` or `MUSSA-data`; `train_segmentation.py` parses (compile it) and its `--help` text lists every option above (import the argument parser builder through `importlib` after stubbing `torch` and `segmentation_models_pytorch` in `sys.modules`); the notebook is valid JSON with the cell order above and its code cells contain the Zenodo URL and the md5.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement the three files.** `train_segmentation.py` builds a torch `Dataset` from `ArcadeSplit` + `preprocess` (augmentation applied to image and masks together: brightness, contrast, gamma, shift up to 5%, scale 0.9 to 1.1, rotation up to 10 degrees; no flips), uses `smp.Unet(encoder_name, encoder_weights="imagenet", in_channels=1, classes=25)`, a loss that is BCE-with-logits plus soft Dice, and AdamW with a cosine schedule.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Smoke test the training script for real** in a throwaway virtual environment outside the project (CPU PyTorch + segmentation-models-pytorch): run it with `--smoke` on the local `arcade/` copy; expected: it finishes, writes `segments.onnx` and `segments.card.json`, and onnxruntime loads the file with output shape `(1, 25, 128, 128)`. Record the outcome in the ledger. If the ImageNet weights cannot be downloaded in the environment, fall back to `encoder_weights=None` for the smoke test only and say so.
- [ ] **Step 6: Commit** `feat(ai): ARCADE training kit and cloud notebook`.

---

### Task 4: ONNX segmenter

**Files:**
- Create: `src/cagsyntax/ai/segmenter.py`; modify `pyproject.toml` (add `onnxruntime`)
- Test: `tests/ai/test_segmenter.py`

**Interfaces:**
- Consumes: `preprocess`, `resize_mask`, `SEGMENT_NAMES`.
- Produces: `class ModelUnavailable(Exception)` (message is user-facing); `@dataclass ModelCard(trained_on: str, trained_at: str, input_size: int, classes: list[str], val_mean_dice: float | None, test_mean_dice: float | None, notice: str)`; `class Segmenter` with `load(model_path: Path) -> Segmenter` (classmethod; reads the sibling `<name>.card.json`; raises `ModelUnavailable` for a missing file, an unreadable or non-ONNX file, a missing or unreadable card, a card whose `classes` differ from `SEGMENT_NAMES`, or a model whose input is not `[N, 1, size, size]` or whose output is not `[N, 25, size, size]` with the card's size), attributes `card`, and `predict(frame: np.ndarray, threshold: float = 0.5) -> np.ndarray` returning a bool array `(25, H, W)` in the frame's own size (preprocess, run, sigmoid, threshold, `resize_mask` per channel). Tests build tiny ONNX models with the `onnx` package (a model that outputs `[N, 25, size, size]` constant logits for two channels positive and the rest negative); add `onnx` to the test requirements.

- [ ] **Step 1: Write failing tests**: loading a good tiny model and card works and `predict` on a 100 x 80 frame returns `(25, 100, 80)` bool with exactly the positive channels set; the threshold argument changes the result; a missing model file, a file of random bytes, a model without a card, a card with the wrong class list, a model with 24 output channels (Review Focus 2) and one with the wrong input shape each raise `ModelUnavailable` with a message naming the problem; `predict` does not modify its input; the same frame twice gives identical output.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `Segmenter`** with `onnxruntime.InferenceSession(..., providers=["CPUExecutionProvider"])` and strict shape checks against the session's input and output metadata.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(ai): ONNX segmenter with strict model checks`.

---

### Task 5: Evaluation

**Files:**
- Create: `src/cagsyntax/ai/evaluate.py`, `tools/ai/evaluate_segmentation.py`
- Test: `tests/ai/test_evaluate.py`

**Interfaces:**
- Consumes: `ArcadeSplit`, `Segmenter` (or any object with `predict(frame) -> (25, H, W) bool`), `per_segment_scores`.
- Produces: `@dataclass EvalReport(split: str, images: int, per_segment: dict[str, dict], macro_dice: float, macro_iou: float, segments_evaluated: int)` and `evaluate_model(segmenter, split: ArcadeSplit, limit: int | None = None, progress=None) -> EvalReport`, where per-segment Dice and IoU are computed from pixel counts summed over all images (not averaged per image), `macro_*` average over the segments that occur in the ground truth or the prediction, and `limit` evaluates the first N images. `report_to_markdown(report) -> str` and `report_to_json(report) -> dict`. The command line tool `python tools/ai/evaluate_segmentation.py --model <onnx> --split <folder> [--limit N] [--out <folder>]` prints the table and writes `report.json` and `report.md`.

- [ ] **Step 1: Write failing tests** with a fake segmenter that returns the ground truth (macro Dice 1.0), one that returns all-false (Dice 0 for every present segment, `segments_evaluated` equal to the number of present segments) and one that predicts a half of each mask (Dice 2/3); pixel-count pooling (an image where a segment is large and one where it is small is weighted by pixels, not averaged per image: construct a case where the two methods differ); absent segments are excluded from the macro average; `limit` works; the markdown table lists all 25 segments in order; the command line tool runs end to end with a toy ONNX model on the synthetic split from Task 1 and writes both files.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `evaluate.py` and the tool.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(ai): evaluate a segmentation model on ARCADE`.

---

### Task 6: Overlay in the viewer and the app

**Files:**
- Create: `src/cagsyntax/ai/overlay.py`
- Modify: `src/cagsyntax/viewer/widget.py`, `src/cagsyntax/app.py`
- Test: `tests/ai/test_overlay.py`, `tests/test_ai_app.py`

**Interfaces:**
- Produces in `overlay.py`: `SEGMENT_COLORS: dict[str, tuple[int, int, int]]` (25 distinct colours) and `render_overlay(masks: np.ndarray, alpha: int = 110) -> np.ndarray` returning uint8 `(H, W, 4)` RGBA (transparent where no mask; where masks overlap, the later segment in table order wins); `segment_labels(masks: np.ndarray) -> list[tuple[str, float, float]]` giving segment name and centroid (x, y) for each non-empty mask.
- Modifies `CineWidget`: `set_overlay(rgba: np.ndarray | None, labels: list | None = None, caption: str = "")` draws the RGBA over the current frame (same size as the frame) with the labels and the caption "AI suggestion - not a diagnosis" always drawn in a corner; `clear_overlay()`; `overlay_visible() -> bool`; changing the frame clears the overlay unless a cached overlay for that frame is supplied by the window.
- Modifies `MainWindow(data_dir, segmenter: Segmenter | None = None)`: when `segmenter` is None it tries `Segmenter.load(data_dir / "models" / "segments.onnx")` and keeps the failure message in `self.segmenter_error`; a toolbar toggle "AI segments" (checkable). `toggle_ai_segments(on: bool) -> bool` returns whether the overlay is now shown; with no usable model it stays off, says why in the status bar (naming `docs/ai-training.md`) and shows no dialog on startup; with a model it runs `predict` for the displayed frame (wait cursor), caches per (series path, frame index) and draws the overlay; moving to another frame or series refreshes it while the toggle is on; an exception from `predict` is reported ("AI segments failed: ...") and the overlay is switched off.

- [ ] **Step 1: Write failing tests**: `render_overlay` shape, dtype, transparency where empty, the later segment winning on overlap, 25 distinct colours; `segment_labels` centroids for two simple masks; the widget shows the caption whenever an overlay is set (Review Focus 3) and `clear_overlay` removes everything; without a model file `MainWindow(...)` opens normally, `segmenter_error` is set, `toggle_ai_segments(True)` returns False and the status bar names the docs file (Review Focus 1); a corrupt model file in `models/` gives the same; with an injected fake segmenter returning a known mask, toggling on shows the overlay for the displayed frame, stepping to the next frame refreshes it, the cache avoids a second `predict` call for the same frame (count calls), toggling off clears it; a `predict` that raises is reported and leaves the overlay off; toggling the overlay never changes the case store, the saved scores or the series list (compare before and after) (Review Focus 3).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the overlay module, the widget changes and the window changes. Frame data for prediction comes from the series already loaded in the widget; the frame shown is the one with `player.index`.
- [ ] **Step 4: Run** `python -m pytest -q`. Expected: all PASS.
- [ ] **Step 5: Manual check:** launch the app without a model and click "AI segments" (expect the explanatory message); with the smoke-test model from Task 3 installed in `MUSSA-data/models/`, click it on a cine (expect an overlay, and a visibly poor one, since the smoke model is barely trained).
- [ ] **Step 6: Commit** `feat(app): AI segment overlay on the viewer`.

---

### Task 7: Documentation

**Files:**
- Create: `docs/ai-training.md`; modify `docs/user-guide.md`, `docs/specs/2026-11-20-cag-syntax-ai-design.md`

- [ ] **Step 1: Write `docs/ai-training.md`:** what ARCADE is and its limits (single frames, no cines or angles, the two tasks use different images, unknown annotation process, no ethics statement); step by step: build the kit (`python tools/training/make_kit.py`), open the notebook on Google Colab or Kaggle with a GPU, run all cells, download the two files, copy them to `C:\Users\<you>\MUSSA-data\models\`; how to evaluate (`python tools/ai/evaluate_segmentation.py ...`); how to read the model card; expected modest accuracy; what the overlay is and is not.
- [ ] **Step 2: Update spec section 6** with the decided segment-helper design (data, model, splits, evaluation, overlay, offline inference) and the user guide with a short "AI segments" section.
- [ ] **Step 3: Run** `python -m pytest -q`. Expected: all PASS.
- [ ] **Step 4: Commit** `docs: AI segment helper, training and evaluation guide`.

---

## Self-Review

- **Spec coverage:** Phase B helper 2 (vessel and segment segmentation on key frames) is Tasks 1 to 6; overlay "marked as AI-suggested" (6) is Task 6; start from public data with licensing checked (6) is the Global Constraints and Task 3; offline at runtime and no cloud for patient data (2, 4) is the Decisions and Task 4; evaluation on held-out data (6) is Task 5. Not covered here, by design: helper 3 (stenosis), form pre-filling, accept/edit logging, fine-tuning on confirmed cases, the timing and agreement comparison. Helper 1 (view labels from angles) already exists from step 1.
- **Type consistency:** `SEGMENT_NAMES` (Task 1) is used by Tasks 2, 4, 5 and 6; `preprocess`/`resize_mask` (Task 2) by 3 and 4; `Segmenter`/`ModelUnavailable`/`ModelCard` (Task 4) by 5 and 6; `render_overlay`/`segment_labels` (Task 6) only by the viewer and app.
- **Honest limits:** the real model is trained by the user in the cloud, so this plan can prove the pipeline (a smoke-trained toy model, tests with tiny models) but not the accuracy; the evaluation tool exists to measure it afterwards. ARCADE's segment labels cover single frames, so accuracy on the hospital's cines may differ.
- **Open risks:** ImageNet weights and `segmentation-models-pytorch` need internet in the notebook; ARCADE's annotation quality is undocumented; the 512 x 512 inference on this PC's CPU has not been timed yet (Task 6 Step 5 measures it).
