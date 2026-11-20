# CAG SYNTAX Assistant: Design Spec

Date: 2026-11-20
Status: Draft for review
Scope: Phase A (scoring tool) and Phase B (AI suggestions). "Need for CAG" prediction is out of scope and gets its own spec.

## 1. Goal

A desktop app that lets clinicians review coronary angiogram DICOM (XA) series, record findings in a structured form, and compute the SYNTAX score with a transparent, tested rule engine. Every confirmed case becomes a labeled example. Phase B adds AI that pre-fills the form with suggestions that a clinician accepts or edits.

## 2. Non-goals

- No automatic diagnosis. A cardiologist confirms every score.
- No end-to-end model that predicts a score directly from images.
- No SYNTAX II (clinical variables) in this version.
- No "need for CAG" prediction (clinical, ECG, stress-test or CCTA inputs). Separate spec.
- No cloud processing. Patient images stay on the hospital machine.

## 3. Users and data

- Scorers: several people of mixed experience (residents and cardiologists). The tool records who scored each case and their experience level.
- Reference label: the version confirmed by a cardiologist.
- Data: raw XA cine DICOM exported from the cath lab, no existing annotations. Expected volume: 100 to 500 cases over the next few months.
- Non-XA DICOM (for example the X-Ray Radiation Dose SR, or a Secondary Capture whose modality is not XA) is rejected on import with a clear message.

### 3.1 What matters most

- **Cine series are the primary data.** A cine is a multi-frame XA image: one contrast injection filmed from one fixed C-arm angle. Scoring decisions (lesion present, stenosis of 50% or more, total occlusion, bifurcation, calcification and the rest) are made by scrubbing a cine to its best-opacified frames. Phase B models train and are evaluated on cine frames.
- **The C-arm angles of each cine come second.** They give the view label (for example RAO 27 CRAN 18), which tells the scorer which segments that view can show.
- **Stills are secondary reference only.** A still is a single-frame Secondary Capture image with modality XA, saved by the operator as a key frame (it has angles but no frame timing). The app accepts it, labels it STILL, and lists it after the cines of its folder. A still is never counted as a cine, and the dataset export (section 5.3) leaves stills out unless asked for them.
- Everything else is rejected with a clear message.

## 4. Platform

Python, PySide6, SQLite, Windows desktop. Same stack as the author's other desktop apps. Runs fully offline.

## 5. Architecture (Phase A)

Five independent units. Each communicates only through the interfaces shown.

| Unit | Does | Depends on |
|---|---|---|
| DICOM import | Reads XA series with pydicom, de-identifies, reads C-arm angles (positioner primary and secondary) to label each view, rejects non-XA files | pydicom |
| Viewer | Cine playback, frame stepping, zoom | DICOM import output |
| Scoring form | Collects dominance, diseased segments (the full 25 sub-segments, see 5.2) and lesion features | none (pure data entry) |
| Scoring engine | Pure function: form data in, score and breakdown out. No UI, no AI | official SYNTAX tables |
| Case store | SQLite. Saves each scorer's entry, scorer identity and level, timestamps, confirmed version | none |

### 5.1 DICOM import

- Strip patient name, ID, birth date and other direct identifiers on import. Store a salted hash of the MRN so repeat cases can be linked.
- Keep study date, modality, series description and positioner angles.
- A scan test checks the stored output for leftover identifiers.
- Unsupported or corrupt files produce a visible error, never a silent skip.
- Each imported series is marked CINE (with its frame count) or STILL, and the list shows cines before stills within each folder.

### 5.2 Scoring form and engine

- Rules follow SYNTAX I: lesions with 50% or more diameter stenosis in vessels of 1.5 mm or larger.
- Segments (decided): the full 25 sub-segments used by the official calculator: 1, 2, 3, 4, 5, 6, 7, 8, 9, 9a, 10, 10a, 11, 12, 12a, 12b, 13, 14, 14a, 14b, 15, 16, 16a, 16b, 16c. Segments that do not apply to the chosen dominance are hidden.
- Inputs: coronary dominance (right, left, co-dominant), segment selection, and per-lesion features: total occlusion (with its sub-features), bifurcation (with type and angle), trifurcation, aorto-ostial, severe tortuosity, length over 20 mm, heavy calcification, thrombus, diffuse disease or small vessels.
- Output: total score, group (low 22 or below, intermediate 23 to 32, high 33 or above), and a per-lesion breakdown showing how each lesion contributed.
- Segment weights and modifiers are taken from the official published SYNTAX tables during implementation, not from memory. The source and version used are recorded in the code.
- **Source and version (decided):** weights and rules are transcribed from the official calculator, version 2.28 (`https://syntaxscore.org/calculator/syntaxscore/javascript/frameset.js`), and recorded in `scoring/tables.py`. The 2005 paper was not consulted.
- **Co-dominance (decided):** the official score has no co-dominant table. The case records dominance as right, left or co-dominant; for co-dominant the scorer must choose right or left as the scoring table, and the result shows both. A co-dominant case with no scoring table is incomplete.
- **Rules that follow the official form (decided):** a total occlusion has exactly one marked first segment (x5; other segments x2). After a total occlusion, trifurcation and bifurcation are asked only when the side branch is 1.5 mm or larger or both sizes. The "first segment beyond the occlusion" question is asked only when the occlusion's main segment has more than one candidate, and it follows the official lookup table and its special cases. At most 12 lesions. Diffuse disease scores 1 per marked segment for the whole case, outside the per-lesion totals.
- **Groups:** low 22 or below, intermediate 23 to 32, high 33 or above; a fractional total between the cut-offs (for example 22.5 or 32.5) is intermediate. Fractional totals occur when an occlusion of a 0.5-weight segment is multiplied by 5. A clinician should confirm this reading of the published groups.
- **Verification (done):** the engine was compared with the official calculator's own JavaScript, run locally in a sandbox over 700 generated cases (every occlusion main segment x every beyond-occlusion option x both dominances, plus random cases). The engine matches all 700. The golden file is `tests/scoring/golden.json`; official-code quirks that were not copied are listed in `tests/scoring/KNOWN_OFFICIAL_QUIRKS.md`.
- The engine rejects impossible combinations (for example an occlusion on an unmarked segment). A case with missing required fields is marked incomplete and gets no final score.

### 5.3 Case store

- One record per case. Multiple scorer entries per case. One confirmed entry per case, set by a cardiologist.
- Disagreement tracking: the app reports how often scorers differ from the confirmed version, per scorer level.
- Export: confirmed cases as a dataset (de-identified image references plus form data and score) for Phase B. Cine series only by default; stills are excluded unless the user asks for them.
- **Case (decided):** a case is one imported study, identified by the (remapped) study UID of its stored series. All series of a study belong to one case. Cases and scores are kept in `cases.sqlite` next to the image store and do not depend on the viewer list: deleting and re-importing series keeps the scores.
- **Scorers (decided):** named profiles (name and level, resident or cardiologist) are kept in the case store. The app asks for a scorer before scoring and remembers the last one. There is no password; access control is the Windows account on the hospital machine (section 7). Only a cardiologist can confirm.
- **Entries (decided):** each scorer has one entry per case, updated in place with a new timestamp. Incomplete or invalid entries can be saved as drafts, but only a complete entry can be confirmed. Confirming stores a snapshot of the entry, so later edits do not change the reference.
- **Disagreement (decided):** measured on the final total and group against the confirmed snapshot, per scorer level, excluding the confirmed entry itself, incomplete entries and cases without a confirmation. Two scorers who reach the same total through different lesions count as agreeing; a per-lesion or per-segment comparison is left for a later step.
- **Form (decided):** one segment picker (a schematic tree, not an anatomical drawing), one control per applicable question, and the engine's live result. Answers that stop applying (for example trifurcation after the side branch is changed to under 1.5 mm) are cleared automatically; segments that do not exist for a new dominance are removed and the scorer is told which. There is no free-text comment field, because free text invites patient identifiers. The form always shows that this is an educational tool, not a certified medical device.

## 6. Phase B: AI suggestions

The AI only suggests. It never changes the scoring engine.

Order of work, one helper at a time:

1. View labeling from C-arm angles. Rule-based, no AI.
2. Vessel and segment segmentation on key frames.
3. Stenosis candidates with an estimated percentage.

Behavior:

- Suggestions appear as overlays and pre-filled form fields, marked as AI-suggested.
- The scorer accepts or edits each one. Accepts and edits are logged, because they are further training signal.
- Items that depend on clinical judgment (occlusion age, collateral filling and similar) stay manual.

Training:

- Start from a model trained on public coronary angiography data. Check dataset licensing and fit before use.
- Fine-tune on the confirmed cases (target 100 to 500). This size supports fine-tuning and testing, not training from scratch. Expect modest accuracy at first.

Evaluation:

- Hold out test cases, with all images of one patient kept in the same split.
- Compare to the confirmed version on: per-segment detection of 50%-or-more stenosis (sensitivity and specificity), and agreement on the final score group.
- Compare AI-assisted entry time and scorer agreement against manual entry.

## 7. Safety, ethics and data handling

- Labeled as decision support for research and teaching. Not a certified medical device.
- Ethics committee approval or a documented waiver is required before using patient images.
- De-identification happens on import, before anything is stored.
- Access to the case store is limited to named users on the hospital machine.

## 8. Testing

- Scoring engine: unit tests built from worked examples in the official SYNTAX calculator. Engine output must match on every example before any clinical use.
- DICOM import: test files covering valid XA, non-XA (including the dose SR), corrupt and missing-angle cases.
- De-identification: automated scan for identifiers in stored output.
- Phase B: offline evaluation on held-out cases as in section 6.

## 9. Build order, with a review stop after each step

1. DICOM import, de-identification and viewer
2. Scoring engine with tests against the official calculator
3. Scoring form and case store
4. Dataset export of confirmed cases
5. Phase B, one AI helper at a time

## 10. Open items

- Which public dataset to start Phase B from (licensing and image-format fit to be checked at step 5).
- Whether the hospital has an ethics process for retrospective image use, and who approves it.
- Where the cath-lab exports will be stored and who copies them.
