# MUSSA user manual

**MUSSA** (Mataram University Syntax Score Assistant) is an offline Windows program for viewing coronary
angiograms, recording a **SYNTAX Score I**, and using AI suggestions to speed that up. Everything stays on
your computer.

> **Important.** MUSSA is educational and research decision support. It is **not a certified medical device**
> and does not replace clinical judgment. The AI only *suggests*. A person decides every answer, and the SYNTAX
> Score is always calculated by MUSSA's own checked scoring engine, never by the AI.

Short task-by-task steps are in `docs/user-guide.md`. This manual explains the whole program, how to get the most
out of it, and how to make the AI better.

---

## Part 1. What MUSSA does

| Area | What you get |
|---|---|
| Viewer | Import DICOM angiograms, play cine series, zoom, pan, step frame by frame |
| De-identification | Patient identifiers removed at import; your originals are never touched |
| Scoring | Full SYNTAX Score I form: 25 segments, up to 12 lesions, guided questions, live total and risk group |
| Team workflow | Scorers (resident or cardiologist), saved drafts, confirmed reference scores, disagreement statistics |
| AI help | Segment overlay, single-frame **Suggest lesions**, whole-case **Run AI on study** |
| Research export | Confirmed cases as `dataset.json`, CSV files and optional de-identified images |
| Your own AI | Tools to label your own cases and train better models |
| Look and feel | Green/yellow glossy design with an **Appearance** window |

What the AI never does: choose dominance, answer a lesion question, save, score, or confirm anything.

---

## Part 2. Installing and starting

- **This PC:** double-click `Run MUSSA.bat` and keep the black window open.
- **Another PC:** build the portable program (`python tools/packaging/build_exe.py --zip`), copy the zip, unzip,
  run `MUSSA\MUSSA.exe`. No Python or internet needed. Details: `docs/install-on-another-pc.md`.
- **Check it works:** `MUSSA.exe --selftest` (or `python -m cagsyntax.selftest`) lists its checks and ends with
  "Self-test passed".

Your data lives in `C:\Users\<you>\MUSSA-data`:

| Item | What it is |
|---|---|
| `store\` | de-identified images |
| `cases.sqlite` | scores, confirmations, AI logs (the store keeps an automatic `.bak` backup before any upgrade) |
| `salt.key` | the key that links repeat patients. Copy it **together with** `cases.sqlite`, never alone |
| `models\` | the AI model files |
| `theme.json` | your saved look |

---

## Part 3. A tour of the window

- **Left:** the folder filter and the list of series. A coloured square marks scored studies:
  green = reference confirmed, orange = complete score but no reference, grey-blue = draft, none = not scored.
- **Centre:** the viewer. Mouse wheel zooms, drag pans, the slider and arrow buttons step through frames.
- **Right:** the Scoring panel (segment tree, lesion questions, result box).
- **Toolbar, first row:** Import file, Import folder, Rename folder, Delete series, Delete folder, AI segments,
  Appearance.
- **Toolbar, second row:** Add scorer, Score case, Suggest lesions, Run AI on study, Disagreements, Export dataset.
- **Status bar (bottom):** short messages. Read it when something does not seem to happen; it says why.

---

## Part 4. Everyday use

### 4.1 Import
**Import folder** (or **Import file**), give the folder a short name such as `Case 01` (no patient names).
Series are labelled `CINE` or `STILL`. A series marked "check burned-in text" may have patient text in its
pixels. Look at it before sharing anything. Deleting a series or folder only removes MUSSA's copy.

### 4.2 Scorers
**Add scorer**, enter a name and a level (resident or cardiologist). Pick yourself in the **Scorer** box before
scoring. Only a cardiologist can confirm a reference score.

### 4.3 Scoring a case
1. Select any series of the study and click **Score case**.
2. Choose **dominance** (for co-dominant, choose which table to score with).
3. Click diseased segments on the tree (lesions of 50% or more in vessels 1.5 mm or larger). **Add lesion** for more.
4. Answer the enabled questions. Greyed questions do not apply; answers that stop applying clear themselves.
5. Mark diffuse disease or small vessels at the bottom if relevant.
6. Read the result box: total, risk group, points per lesion, or what is still missing. A form with missing
   answers has no score.
7. **Save score** (drafts are allowed; saving again updates your entry).

Safety nets: the panel title names the open case, it will not silently switch case when you have unsaved edits,
and it asks before discarding changes.

### 4.4 Confirming and comparing
- A cardiologist selects a saved complete score and presses **Confirm selected score as reference**.
- **Disagreements** shows how often residents' and cardiologists' totals and risk groups match the references.
  Use it for teaching and for judging whether the scoring is consistent.

### 4.5 Export for research
**Export dataset** writes confirmed cases into a new folder (`dataset.json`, `cases.csv`, `series.csv`,
`README.txt`, optionally de-identified images with checksums). It never contains scorer names, folder names,
original IDs or file paths, and never overwrites an existing folder. Keep exports on the same protected computer.
Format: `docs/dataset-format.md`.

---

## Part 5. The AI features

MUSSA uses two models. Both need files in `MUSSA-data\models\`:

| Model | Files | Question it answers |
|---|---|---|
| Segment model | `segments.onnx`, `segments.card.json` | Where are the 25 coronary segments? |
| Stenosis model | `stenosis.onnx`, `stenosis.card.json` | Where are the narrowings? |

Without them the AI buttons just explain what is missing and change nothing.

### 5.1 AI segments (overlay)
With a series open and paused, click **AI segments**. The segments are outlined on that frame under the label
"AI suggestion - not a diagnosis" (about half a second per frame). It changes no score.

### 5.2 Suggest lesions (one frame)
In the scoring panel, pause on the frame that shows a narrowing best and click **Suggest lesions**. Tick the
narrowings you agree with and add them. Each becomes a lesion with **only the segment filled in**.

### 5.3 Run AI on study (whole case)
Click **Run AI on study** (needs an open case, a chosen scorer, and both models).

1. MUSSA runs both models on every series of the open case (only that case; one patient's findings can never reach
   another patient's form).
2. The proposals window lists one possible narrowing per segment: the model score, the views it was seen in, the
   best frame, and a "check:" note when something needs your eye (a busy bifurcation area, a low score, views that
   disagree, two narrowings in one frame).
3. Select a row and press **Show in viewer** to jump to the exact series and frame behind it.
4. Tick the ones you agree with (nothing is pre-ticked) and press **Add N ticked to the form**.
5. You answer dominance and everything else, then **Save score**.

If narrowings were found outside every outlined segment, or some files could not be read, MUSSA says so instead of
reporting "nothing found". Cancelling records nothing.

What is logged: the AI's raw proposal for the study, which lesions it proposed, which reached the form, the model
files, and who ran it. Your own answer is stored separately as your saved score. This is how the AI's accuracy can be
measured later.

### 5.4 How to read the AI's numbers
- **Model score** is how strongly the model responds, **not** a stenosis percentage and not a probability of disease.
- The AI does not measure stenosis percentage, vessel diameter, lesion length, calcification, thrombus, or dominance.
  Those stay empty for you to fill in.
- Current limits: the segment model is modest (Dice 0.463 on the public test set) and the stenosis model has to be
  trained first. Treat suggestions as a prompt to look, never as a finding.
- The program looks at the **middle frame** of each series. If that frame has no contrast, the AI may miss
  narrowings. Use **Suggest lesions** on a well-filled frame to compensate.

---

## Part 6. Getting the most out of MUSSA

**Speed up scoring**
- Use **Run AI on study** first to get candidate segments, then spend your time on the questions, which the AI
  cannot answer.
- Use **Show in viewer** to verify each proposal in seconds instead of scrolling cine runs.
- Keep folders per patient or per batch with short names, so the list stays readable.

**Improve reliability**
- Have two scorers (resident and cardiologist) score the same cases, then confirm references. **Disagreements**
  then shows where training is needed.
- Confirm a reference only after checking the complete score; later edits do not change a confirmed reference.
- Save drafts often; each save is a recoverable entry.

**Protect your data**
- Back up `MUSSA-data` (both `cases.sqlite` and `salt.key`) regularly.
- Check "burned-in text" series before exporting or sharing.
- Do not move data between PCs by copying only one of the two files.

**Make it yours**
- **Appearance** lets you change the look; copy `theme.json` to other PCs to match.

---

## Part 7. How to improve the AI

The AI improves in three ways: better training data, better measurement, and better use of the logs MUSSA keeps.
Full step-by-step instructions: `docs/labelling-and-training-guide.md` and `docs/ai-training.md`.

### 7.1 Route A: train on the public ARCADE dataset (no patient data, no approval)
1. `python tools/training/make_kit.py` builds `tools\training\dist\mussa-training-kit.zip`.
2. Open `tools\training\MUSSA_train_both_models.ipynb` in Google Colab, set the runtime to **GPU**, **Run all**,
   upload the kit when asked (about 2 to 3 hours, mostly waiting).
3. Download the four files and put them in `C:\Users\<you>\MUSSA-data\models\`.
4. Check with `python -m cagsyntax.selftest`.

**Do this first:** the stenosis model is untrained until you run it, and the segment model is the weakest link.

### 7.2 Measure before you trust
- `python tools/ai/evaluate_segmentation.py --model ...\segments.onnx --split arcade/arcade/syntax/test` prints Dice per
  segment. Above 0.6 is usable as a rough guide; near 0 means the model does not find that segment.
- `python tools/ai/tune_thresholds.py ... --write` tunes the cut-offs on the validation set; re-measure on test.
- The stenosis model's own test score is in `stenosis.card.json` (`test_mean_dice`).

### 7.3 Route B: train on your own cases (needs ethics approval first)
Only after written approval from your ethics committee (including for Colab and the labelling tool):
1. Import cases into MUSSA (they are de-identified on import).
2. `python tools/labelling/mussa_labels.py frames ...` exports one PNG per series. Series with possible burned-in
   text are skipped until you check them. Prefer a **well-filled frame** over the middle frame (`--frame N`).
3. Label in CVAT (ideally on your own PC): polygons for each visible segment, and `stenosis` polygons for narrowings
   of 50% or more. Label the rare branches too (16a, 16b, 16c, 9a, 10, 12, 12b, 14, 14a, 14b, 15). They are where the
   models are weakest.
4. Export COCO 1.0, then `mussa_labels.py check` until it says `OK`, then `split` (keeps each study in one set).
5. Re-run the Colab notebook with `USE_OWN_DATA = True` to fine-tune.
6. Compare old and new models on the same test images, and on cases kept out of training. Replace the installed
   models only if the numbers are better. Keep each model file, card and date.

Targets: 100 to 200 labelled frames is a useful first goal. Variety (patients, machines, projections) matters more
than many frames from one patient.

### 7.4 Use the logs
Every Suggest and Run AI action is recorded with the models used. Review which segments the AI proposes that scorers
reject, and which they add themselves. Those patterns show exactly what to label more of.

### 7.5 What would improve the AI most (roadmap)
1. Train the stenosis model and a stronger segment model (Route A, then Route B).
2. Choose the **contrast-filled key frame** per series instead of the middle frame.
3. Draw the narrowing's box on the shown frame.
4. Add measurements (QCA stenosis percentage, vessel diameter), then morphology and dominance.
5. An optional language-model helper to explain proposals (off by default; needs a stronger PC).

---

## Part 8. Troubleshooting

| Symptom | What to do |
|---|---|
| A button seems to do nothing | Read the status bar; it says what is missing (case, scorer, model, scoring panel hidden) |
| "No segment/stenosis model installed" | Put both files of each pair in `MUSSA-data\models\` and restart |
| "Open a case with Score case first" | Select a series and click **Score case** |
| Suggestions look wrong | Expected from a weak model. Measure it (7.2) and retrain (7.1, 7.3) |
| "AI analysis failed" | The message names the cause; nothing was changed. Check the model files and the series |
| Some series skipped in a run | The proposals window lists them; check those files |
| Save failed ("NOT SAVED") | Disk full or file locked; nothing changed. Fix and press **Save score** again |
| Moved to a new PC and cases are missing | Copy `cases.sqlite` **and** `salt.key` together |

---

## Part 9. Glossary

- **SYNTAX Score I:** a score of the anatomical complexity of coronary disease, from segments, lesions and their features.
- **Segment:** one of the numbered parts of the coronary tree (1 to 16c).
- **Dominance:** which artery supplies the back of the heart (right, left, or co-dominant).
- **Confirmed reference:** a cardiologist-approved complete score used as ground truth.
- **Dice:** overlap measure from 0 to 1 between a model's outline and the human outline.
- **Model score:** the stenosis model's response strength; not a percentage.
- **De-identified:** patient identifiers removed or replaced by anonymous codes.

---

*MUSSA is educational and research decision support, not a certified medical device. All AI output is a suggestion.*
