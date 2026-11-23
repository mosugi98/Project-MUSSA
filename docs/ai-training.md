# AI segment helper: training and using the model

This is the first AI helper of the project (spec Phase B): it outlines the 25 SYNTAX coronary
segments on the frame you are viewing, as a coloured **AI suggestion** overlay. It is decision support
for research and teaching, not a certified medical device and not a diagnosis. It never changes a score,
a form or any stored data.

The app does not ship with a trained model. You train one once, on a free cloud GPU, using only the
public ARCADE dataset, and copy two small files into the app's data folder. Without them the app works
exactly as before and the **AI segments** button explains what is missing.

## The data: ARCADE

- Source: https://zenodo.org/records/10390295 (DOI 10.5281/zenodo.10390295), licence CC0 (public domain).
  Authors from Mohamed Bin Zayed University of Artificial Intelligence, Nazarbayev University and CMC
  Technologies, 2023. File `arcade.zip`, 451.6 MB, md5 `c5b1973ade06f7dff210f878161e1a76`.
- The `syntax` folders (train 1000, val 200, test 300 images) outline the 25 SYNTAX segments in COCO
  polygon format. The `stenosis` folders (same sizes, different images) outline narrowed regions; they are
  not used by this helper.
- Limits you should know: single 512 x 512 frames (no cines, no C-arm angles); the segment images and the
  stenosis images are different sets; how the annotations were made is not described beyond "medical
  experts"; the page has no ethics, consent or de-identification statement; the dataset article was still
  "to be provided later". Your hospital's images may look different, so accuracy on them can differ from
  the numbers measured on ARCADE.
- The ARCADE folder in this project (`arcade/`) is ignored by git. The notebook downloads its own copy.

## Train the model (about an hour on a free GPU)

1. Build the training kit on this PC: `python tools/training/make_kit.py`. This writes
   `tools/training/dist/mussa-training-kit.zip`. The kit holds only code (the training script and copies of the
   app's loader, preprocessing and metrics). No patient data, no hospital files.
2. Open `tools/training/MUSSA_train_both_models.ipynb` on Google Colab (upload it at colab.research.google.com,
   then Runtime > Change runtime type > GPU) or on Kaggle (a notebook with the GPU accelerator).
   On Kaggle, turn on the GPU accelerator and Internet in the notebook settings and add `mussa-training-kit.zip` as a
   dataset (Add data > Upload); the notebook finds it under `/kaggle/input`. On Colab it asks you to upload the zip.
3. Run all cells. The notebook installs `segmentation-models-pytorch`, downloads ARCADE from Zenodo and
   checks its md5, asks you to upload `mussa-training-kit.zip`, trains (up to 60 epochs, stopping early when the validation
   score stops improving; try adding `--smoke` to the training command first for a one-minute pipeline check), and offers two files for download.
   The notebook also checks the exported model by running it once before offering the download. The best weights are
   saved as `segments_best.pt` before the ONNX export, so a failed export does not lose the training run.
4. Copy both downloaded files, `segments.onnx` and `segments.card.json`, into
   `C:\Users\<you>\MUSSA-data\models\` (create the `models` folder if needed). Keep them side by side.
5. Start MUSSA, open a cine, click **AI segments** in the toolbar.

Notes: the notebook needs internet for the ImageNet starting weights that `segmentation-models-pytorch`
downloads (check their terms for research use), and a free account on Colab or Kaggle. Only public ARCADE data
goes to the cloud. Fine-tuning on your own confirmed cases is not part of this step and would stay on this PC.

## What the overlay is and is not

- Coloured, semi-transparent outlines with the segment number, drawn on the shown frame only. It is off by
  default, appears only on a paused frame (not while the cine plays), and always carries the label
  "AI suggestion - not a diagnosis".
- It takes about 0.6 seconds per frame on this PC (measured with a full-size model on the Intel i3-N305). The
  result is cached per frame, so stepping back to a frame is instant.
- It shows where the model thinks each segment is. It does not say which segments are diseased: that is the
  next AI helper (stenosis candidates), planned separately. You score exactly as before.
- Domain gap: ARCADE is all 512 x 512 8-bit frames. A clinical frame that is not square is squashed to a square for the
  model and stretched back, and frames with bright burned-in text or very different contrast can behave differently.
  Series stored with inverted polarity (MONOCHROME1) are now flipped to standard polarity on import, in the viewer too.
- When you turn the overlay on, the status bar names the model and its validation Dice from the model card (a model
  trained with `--smoke` says so there).
- Expect modest accuracy at first. Judge it by looking and by measuring (below), never by assuming.

## Measure the model

```
python tools/ai/evaluate_segmentation.py --model C:\Users\<you>\MUSSA-data\models\segments.onnx ^
    --split arcade\arcade\syntax\test --out segment_eval
```

It runs on the CPU (a few minutes for the 300 test images), prints a table and writes `report.json` and
`report.md`. Dice and IoU per segment are computed from pixel counts pooled over all images; the macro
averages cover the segments that occur. The notebook also prints the validation and test mean Dice. The same
numbers are stored in `segments.card.json` (the model card), together with the training data, date, settings
and a notice.

## If the button says no model is available

The message names the problem: no file in `MUSSA-data\models\`, a missing or unreadable `segments.card.json`,
a file that is not a valid ONNX model, a card that lists different classes than the app's 25 segments, or a
model whose output does not have 25 channels at the card's size. The app checks every model by running it once
when it loads, so a wrong model is refused instead of drawing a wrong overlay.

## Improving a weak model: per-segment cut-offs

A first model often never predicts the rare segments because their probabilities stay below 0.5. Tune a
cut-off for each segment on the validation split (not the test split), then judge on the test split:

    python tools/ai/tune_thresholds.py --model <models folder>\segments.onnx --split arcade/arcade/syntax/val
    python tools/ai/tune_thresholds.py --model <models folder>\segments.onnx --split arcade/arcade/syntax/val --write
    python tools/ai/evaluate_segmentation.py --model <models folder>\segments.onnx --split arcade/arcade/syntax/test

Without `--write` nothing is changed. With it the cut-offs are saved in `segments.card.json` and the app uses
them automatically. If you ever replace the model, tune again: cut-offs belong to one model.

The training script also changed: the loss no longer rewards empty predictions (the first version let the model
collapse to "nothing" for rare segments around epoch 15), positives are weighted (`--pos-weight`), and training
stops early (`--patience`).
