# Labelling and training: step by step

MUSSA uses two AI models. Both are **suggestions** for the scorer; neither calculates the SYNTAX score.

| Model | Question it answers | Trained on | Files |
|---|---|---|---|
| **Segment model** | Where is each of the 25 coronary segments? | ARCADE `syntax` (public, CC0) | `segments.onnx`, `segments.card.json` |
| **Stenosis model** | Where are the narrowings? | ARCADE `stenosis` (public, CC0) | `stenosis.onnx`, `stenosis.card.json` |

Together they power **Suggest lesions**: the stenosis model finds a narrowing, the segment model says which
segment it is in, and you tick the ones you agree with.

There are two routes. **Route A** needs no patient data and no approval. **Route B** adds your own labelled cases
to make the models fit your hospital's images better, and **needs ethics approval first**.

---

## Route A: train both models on ARCADE (no patient data)

Time: about 2 to 3 hours on a free GPU, mostly waiting. You need a Google account.

**Step 1. Build the training kit** (once, and again after any change to the training code). In PowerShell:

    cd "D:\Project Mataram University Syntax Score Assistant (MUSSA)"
    python tools/training/make_kit.py

This writes `tools\training\dist\mussa-training-kit.zip`.

**Step 2. Open the notebook in Colab.** Go to colab.research.google.com, choose **File > Upload notebook**, and
pick `tools\training\MUSSA_train_both_models.ipynb`. Then **Runtime > Change runtime type > GPU > Save**.

**Step 3. Run it.** Choose **Runtime > Run all**. When it asks, upload `mussa-training-kit.zip`. The notebook then:
1. downloads ARCADE (about 1.2 GB) and checks it is intact,
2. trains the **segment model**, then the **stenosis model**. Each prints one line per epoch and stops early when the
   validation score stops improving,
3. skips the optional "own data" cell (it is switched off),
4. checks both models and downloads four files.

If a free session disconnects, run it again; it picks up from the download step. The best weights are saved
before each export, so a failed export loses nothing.

**Step 4. Install the four files.** Put them side by side in `C:\Users\<you>\MUSSA-data\models\` (create the
`models` folder if needed):

    segments.onnx   segments.card.json   stenosis.onnx   stenosis.card.json

**Step 5. Check the install.** Start MUSSA once, or run the self-test from the project folder:

    $env:PYTHONPATH = "src"
    python -m cagsyntax.selftest

The two AI lines should say the models loaded. (With the portable program, run `MUSSA.exe --selftest` instead.)

**Step 6. Measure the models** (so you know how far to trust them). This needs the ARCADE images on your PC:
download `arcade.zip` from https://zenodo.org/records/10390295 and unzip it into the project folder so that
`arcade\arcade\syntax\test` exists. Then:

    python tools/ai/evaluate_segmentation.py --model "C:\Users\<you>\MUSSA-data\models\segments.onnx" --split arcade/arcade/syntax/test

Read the table: a segment with Dice above 0.6 is usable as a rough guide; near 0 means the model does not
find it. The stenosis model's own test score is stored in `stenosis.card.json` (`test_mean_dice`).

**Step 7 (optional). Tune the cut-offs** of the segment model on the validation images, then re-measure on test:

    python tools/ai/tune_thresholds.py --model "C:\Users\<you>\MUSSA-data\models\segments.onnx" --split arcade/arcade/syntax/val --write
    python tools/ai/evaluate_segmentation.py --model "C:\Users\<you>\MUSSA-data\models\segments.onnx" --split arcade/arcade/syntax/test

---

## Using the suggestions in MUSSA

1. **Score case** for the study, with a scorer selected.
2. Open the series and pause on the frame that shows the narrowing best.
3. Click **Suggest lesions** in the second toolbar row. MUSSA looks for narrowings and opens a list.
4. Tick the ones you agree with and press **Add ... to the form**. Nothing is ticked for you.
5. The ticked segments appear as lesions with only the segment filled in. **You** answer dominance, occlusion,
   bifurcation and every other question, then press **Save score**.

MUSSA records every accept and reject (which segment, model score, frame, which model files). This log is how
you will later see where the AI is right and wrong.

---

## Route B: add your own labelled cases

**Stop here unless you have written approval from your hospital's ethics committee** for using these images to
train a model, and for any cloud service you use (Google Colab and the labelling tool both count). Without that,
use Route A only.

You need at least a few hundred labelled frames for a real improvement; with fewer, you can still *fine-tune* the
ARCADE model, which needs less. Start small, measure, add more.

**Step 1. Make sure the cases are in MUSSA.** Import the DICOM files with **Import file / Import folder**. MUSSA
de-identifies them on import. The labelling steps below only ever use MUSSA's de-identified store, never the
original DICOM files.

**Step 2. Export one image per series for labelling:**

    python tools/labelling/mussa_labels.py frames --store "C:\Users\<you>\MUSSA-data\store" --out "D:\labelling\png"

This writes one PNG per series (the middle frame) and `frames.csv`, which links each PNG to its study. The names
contain no patient information. **The pixels might**: some machines burn the patient's name or ID into the image.
Series that are not marked as free of burned-in text are therefore **skipped** and listed. Open those images,
look at the corners, and only if they are clean run the command again with `--include-burned-in`. Use `--frame all` for every frame, or `--frame 12` for a chosen frame. Choose the
frame where the vessels are best filled with contrast; the middle frame is only a starting point.

**Step 3. Set up the labelling tool (CVAT).** CVAT is free. **Run it on your own PC** (CVAT's Docker install
guide is at docs.cvat.ai) if your approval does not cover a cloud service; the public website app.cvat.ai
stores your images on someone else's servers.
1. Create a **Project**. In the label editor choose **Raw** and paste the contents of
   `tools\labelling\cvat_labels.json`. This creates the 25 segment labels (`1`, `2`, ... `16c`) and `stenosis`,
   all as polygons.
2. Create a **Task** in that project and upload the PNG files.

**Step 4. Label.** For each image, draw a **polygon** around:
- each coronary segment you can see, with the label of that SYNTAX segment (the segment map in MUSSA's scoring
  panel shows the numbers and where they are),
- each **narrowing of 50% or more**, with the label `stenosis`.

Rules that keep the labels useful:
- Polygons only. Do not use brush or bitmap tools; the checker rejects them.
- Label only what you can see. Skip a segment that is hidden or unclear.
- Be consistent. If two people label, agree on the rules first and have them label some of the same images.
- A frame with no narrowing is fine for the stenosis model; leave it without `stenosis` polygons.
- Label rare branches too (16a, 16b, 16c, 9a, 10, 12, 12b, 14, 14a, 14b, 15); they are where the models are weakest.

**Step 5. Export.** Choose **Export dataset > COCO 1.0**, tick **Save images**, and unzip into a new folder, for
example `D:\labelling\cvat-export`. It should contain `images\` (the pictures may sit in a subfolder such as `images\default\`; that is fine) and
`annotations\instances_default.json`.

**Step 6. Check the labels.** This explains every problem in plain words:

    python tools/labelling/mussa_labels.py check --folder "D:\labelling\cvat-export"

Fix anything marked `PROBLEM` in CVAT, export again, and re-check until it says `OK`. Warnings are worth reading
(for example, a segment with fewer than 5 examples will barely be learned).

**Step 7. Split into train and validation.** Images of one study must stay together (otherwise the model is tested
on images from a patient it already saw). First copy `frames.csv` from your PNG folder into the export folder, so
MUSSA knows which images belong to the same study:

    copy "D:\labelling\png\frames.csv" "D:\labelling\cvat-export\frames.csv"
    python tools/labelling/mussa_labels.py split --source "D:\labelling\cvat-export" --out "D:\labelling\labelled"

Without `frames.csv` the split treats every image as its own group. Then zip the `labelled` folder as
`labelled.zip` (it must contain `train\` and `val\` at the top).

**Step 8. Fine-tune.** Open the notebook as in Route A. Before running, in the cell called OPTIONAL, change
`USE_OWN_DATA = False` to `USE_OWN_DATA = True`, read its warning, and upload `labelled.zip` when asked. The
notebook starts from the ARCADE models and adds your cases with a gentle learning rate. It writes the improved
models to a second folder and offers those for download instead.

**Step 9. Compare before you trust it.** Install the new files in a separate folder first and run
`evaluate_segmentation.py` on the same ARCADE test images, **and** keep some of your own labelled cases out of
training to test on. Only replace the models in `MUSSA-data\models` if the new numbers are better.

**Step 10. Keep records.** Keep the model files, their `.card.json`, the date and the number of labelled cases for
each version. Your ethics approval may require it, and the cards already record how each model was trained.

---

## How long labelling takes, and how many cases you need

Labelling 25 segments plus narrowings on one frame takes roughly 5 to 15 minutes at first and gets faster. A
useful first target is 100 to 200 frames, then re-measure. Models improve with more varied cases (different
patients, machines, projections), not with more frames from the same patient.

## If something goes wrong

| Symptom | What to do |
|---|---|
| `make_kit.py` or a test fails | Read the message; nothing was changed on your data |
| Colab disconnects | Run all again; it re-uses the download |
| `check` prints `PROBLEM` | Fix it in CVAT and export again; the message names the label and the image |
| A model shows "not installed" in MUSSA | Check the four file names and that both files of each pair sit together in `MUSSA-data\models\` |
| The suggestions look wrong | That is expected from a weak model; measure it (Route A step 6) and retrain or add labelled cases |

All AI output is a suggestion. MUSSA is educational decision support, not a certified medical device.
