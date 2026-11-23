# MUSSA user guide

MUSSA is an educational and research tool for viewing coronary angiograms and recording a
SYNTAX Score. It is **not a certified medical device** and does not replace clinical judgment.
Everything stays on this computer.

Start it by double-clicking `Run MUSSA.bat` (keep the black window open while you work).
The full manual, with tips for getting the most out of MUSSA and improving the AI, is `docs/user-manual.md`.

## 1. Import images

1. **Import folder** (or **Import file**) and choose the DICOM files.
2. Give the folder a short name (for example `Case 01`). Avoid patient names.
3. MUSSA removes patient identifiers while importing. Each series is listed as `CINE` (a movie)
   or `STILL` (a saved key frame). Series marked "check burned-in text" may have patient text in the
   pixels: look at them before sharing anything.

Click a series to play it. Use the arrow buttons, the slider, the mouse wheel to zoom and drag to
pan. **Rename folder**, **Delete series** and **Delete folder** only change MUSSA's own copies;
your original files are never touched.

## 2. Add yourself as a scorer

Click **Add scorer**, type your name and choose your level (resident or cardiologist). Pick your
name in the **Scorer** box whenever you score. Only a cardiologist can confirm a reference score.

## 3. Score a case

A case is one study. Select any series of the study, then click **Score case**.

1. Choose the **dominance**. For co-dominant, also choose whether to score with the right or the
   left table (the official score has no co-dominant table).
2. Click the diseased **segments** on the tree (lesions of 50% or more in vessels of 1.5 mm or
   larger). Add more lesions with **Add lesion** (up to 12).
3. Answer the questions that are enabled. Questions that do not apply are greyed out, and answers
   that stop applying are cleared for you.
4. Mark **diffuse disease / small vessels** segments at the bottom if they apply.
5. Read the result box: the total and risk group, the points for each lesion, or what is still
   missing. A case with missing answers has no score.

The title of the Scoring panel names the case that is open (folder, study date and the last digits
of the case id). If you select a series of a different study, the panel switches to that case only
when nothing is unsaved; otherwise it keeps the open case and the status bar tells you, so a score
can never be saved to the wrong case by accident. MUSSA also asks before it discards unsaved edits
(when you switch scorer, open another case or close the window).

Click **Save score** to keep your entry. If saving fails (for example the file is locked or the disk
is full) you get a warning dialog and the status bar says NOT SAVED; nothing is changed. You can save an unfinished score as a draft and come back
to it; saving again updates your entry.

## Markers on scored series

A small coloured square at the left of a series shows that its study already has saved scores.
Hold the mouse over any series to read what its marker means.

- **Green** - a cardiologist has confirmed a reference score.
- **Orange** - at least one complete score exists, but no reference has been confirmed yet.
- **Grey-blue** - a score was saved, but it is unfinished (a draft).
- **No marker** - not scored yet.

All series of the same study share one marker, and it updates as soon as a score is saved.

## 4. Confirm a reference score (cardiologists)

Every saved score for the case is listed under "Scores saved for this case". Your own score is
selected automatically (or the only score, if there is just one); to confirm someone else's score,
click it in the list first. Then click **Confirm selected score as reference**.

MUSSA asks "Confirm <scorer>'s score (<total>) as the reference?" so you can check what you are
confirming. After you answer Yes, the status bar says "Confirmed as the reference score", the
"Reference score" line appears under the list, and the series of the study get a green marker.

If nothing happens, a message tells you why: only a cardiologist can confirm; only a complete score
can be confirmed; a score must be selected; and unsaved changes to your own score must be saved
first (the saved version is what gets confirmed). Later edits do not change the confirmed reference
(a row edited afterwards is marked), and replacing an existing reference asks first.

## 5. Disagreements

**Disagreements** shows, for residents and for cardiologists, how many scores were compared with
the confirmed references and how often the total and the risk group were the same.

## 6. Export for the AI step

**Export dataset** (second toolbar row) writes every case that has a confirmed reference into a new folder
you name: `dataset.json`, `cases.csv`, `series.csv` and a `README.txt`. It asks two questions:

- **Include still images?** Cine series are always included; stills only if you say yes.
- **Copy the de-identified images into the export?** No keeps paths into MUSSA's data folder (smaller,
  but moving that folder breaks them). Yes copies the images into an `images` folder with a checksum for
  each.

While images are being copied a progress box appears with a **Cancel** button; cancelling leaves nothing
behind. Copied images keep only a short list of DICOM fields (the anonymous IDs, study date, pixels, cine
timing and C-arm angles); descriptions, protocol names, patient sex and age and times are removed. The
README counts series that may have patient text burned into the image: look at those before sharing.

The export never contains scorer names, your folder names, original IDs, MRNs or file paths. It never
overwrites an existing folder: pick a new name. If the current scoring engine disagrees with a confirmed
reference, the case is still exported as confirmed and flagged in the README. The format is described in
`docs/dataset-format.md`.

Keep exports on the same protected computer; they are research data.

## 7. AI segments (suggestion overlay)

If a trained model is installed (see `docs/ai-training.md`), click **AI segments** in the toolbar while a series
is open. The coronary segments are outlined in colour on the shown frame, with their numbers, under the label
"AI suggestion - not a diagnosis". It appears on paused frames only and takes about half a second per frame.

It does not change any score or form, and it does not say which segments are diseased: you still score
exactly as before. Without a model, the button explains what is missing and nothing else changes.

## 8. Suggest lesions (AI narrowings)

With both AI models installed (segments and stenosis; see `docs/labelling-and-training-guide.md`), you can let
MUSSA point at possible narrowings. In the scoring panel, pause on the frame that shows the narrowing best and
click **Suggest lesions** (second toolbar row). A list opens: each line is a possible narrowing, the segment it
lies in, and the model's score (how strongly the model responds, not a certainty). Nothing is ticked. Tick the ones you agree with and press **Add ... to the
form**.

What it does: adds a lesion with only the **segment** filled in, ready for you to complete. What it never does:
choose dominance, answer any question about the lesion, save, score or confirm anything. Candidates outside the
outlined segments are listed but cannot be added. Your accepts and rejects are recorded in the case store, with the
model versions, so the AI's accuracy can be checked later.

Without the models the button explains what is missing and nothing else changes.

## 9. Run AI on study (whole case)

With both models installed, open a case with **Score case**, choose your scorer and click **Run AI on study**.
MUSSA analyses every series of that case and lists one possible narrowing per segment, with the model score, the
views it was seen in, the best frame and any "check:" notes. Select a row and press **Show in viewer** to see the
frame it comes from. Tick the ones you agree with (nothing is ticked for you) and press **Add ... to the form**.
Only the segment is filled in; dominance and every other answer stay yours. If narrowings were found outside the
outlined segments, or a file could not be read, MUSSA says so. Cancelling records nothing; the raw proposal and
what reached the form are stored with the model versions.

## Where your data is

`C:\Users\<you>\MUSSA-data` holds the de-identified images (`store`), folder names, the case store
(`cases.sqlite`) and the key used to link repeat patients. Keep this folder on a protected
computer. Back it up if the scores matter.
