# MUSSA user guide

MUSSA is an educational and research tool for viewing coronary angiograms and recording a
SYNTAX Score. It is **not a certified medical device** and does not replace clinical judgment.
Everything stays on this computer.

Start it by double-clicking `Run MUSSA.bat` (keep the black window open while you work).

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

Click **Save score** to keep your entry. You can save an unfinished score as a draft and come back
to it; saving again updates your entry.

## 4. Confirm a reference score (cardiologists)

Every saved score for the case is listed under "Scores saved for this case". Select one and click
**Confirm selected entry as reference**. The series of that case are then marked `[scored]`.
Only complete scores can be confirmed. Later edits do not change the confirmed reference.

## 5. Disagreements

**Disagreements** shows, for residents and for cardiologists, how many scores were compared with
the confirmed references and how often the total and the risk group were the same.

## Where your data is

`C:\Users\<you>\MUSSA-data` holds the de-identified images (`store`), folder names, the case store
(`cases.sqlite`) and the key used to link repeat patients. Keep this folder on a protected
computer. Back it up if the scores matter.
