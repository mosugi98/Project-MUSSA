# MUSSA dataset export: format

Produced by **Export dataset** in the app (spec step 4). Educational and research use; not a
certified medical device. Everything is de-identified: see "What is left out" and "Burned-in text".

## Folder layout

```
<export folder>/
  dataset.json   full data
  cases.csv      one row per exported case
  series.csv     one row per series of those cases
  README.txt     what the export is, warnings, the split rule
  images/        only when "copy images" was chosen: <series_id>.dcm
```

## dataset.json

| Key | Meaning |
|---|---|
| `format_version` | `1` |
| `created` | date of the export (day only) |
| `engine` | `source` (URL of the official calculator code the engine was checked against) and `version` |
| `options` | `include_stills`, `images_copied` |
| `notice` | the research / not-a-medical-device notice |
| `counts` | `cases`, `series`, `excluded`, `inconsistent`, `burned_in_unclear`, `without_patient_key` |
| `cases` | list, see below |
| `excluded` | confirmed cases that could not be exported: `case_id`, `reason` |

Each entry of `cases`:

| Key | Meaning |
|---|---|
| `case_id` | the study, as a remapped (anonymous) study UID |
| `patient_key` | salted hash of the MRN: all cases of one patient share it. `null` when the files had no MRN |
| `suggested_split` | `train`, `val` or `test` (see "Split suggestion") |
| `confirmed_at`, `confirmed_by_level` | the day the reference was confirmed and the confirmer's level (never a name) |
| `reference` | what was confirmed (see below) |
| `rescored` | the **current** engine on the same form (see below) |
| `series` | list: `series_id`, `kind` (`cine` or `still`), `view` (e.g. "RAO 27 CRAN 18"), `frames`, `study_date`, `burned_in_unclear`, `path`, and `sha256` when images are copied |

`reference` is only what was confirmed: `total`, `group` (low / intermediate / high), `dominance` (right /
left / co-dominant), `scoring_dominance` (the table used), `lesions` (each just its `segments`),
`diffuse_segments`, and `form`, the form data as confirmed (only the known form fields; usable to rebuild
the case).

`rescored` is the current scoring engine run on that form: `total`, `group`, `diffuse_points` and `lesions`
(each with `segments`, `total` and `parts`, the labelled points that add up to the lesion total), plus
`consistent`. The breakdown is only guaranteed to match the reference when `consistent` is true. It is
false when the current engine's total or group differs from the confirmed one (for example after an engine
update), or when the engine now rejects the form (then `total` is `null` and `lesions` is empty). The case
is still exported with the reference as confirmed, and `README.txt` carries a warning.

## cases.csv and series.csv

`cases.csv` columns: `case_id, patient_key, suggested_split, reference_total, reference_group, dominance,
scoring_dominance, n_lesions, n_series, n_cines, consistent_with_engine` (`patient_key` is empty when there
is none).

`series.csv` columns: `case_id, series_id, kind, view, frames, burned_in_unclear, path`. Join the two files
on `case_id`.

## Reading a series

- Without copied images, `path` is relative to the app's data folder (`C:\Users\<you>\MUSSA-data`),
  for example `store/2.25.<digits>.dcm`. Moving or deleting that folder breaks the paths. Those files are
  the app's de-identified copies and carry more header fields than exported images do (for example series
  and study descriptions, protocol names, patient sex and age, times).
- With copied images, `path` is `images/<series_id>.dcm` inside the export and `sha256` lets you check each
  file. Copied images keep **only** an allow-list of DICOM elements: the remapped IDs, `PatientID` (the
  salted MRN hash), `StudyDate`, `Modality`, image geometry and pixel data (with the original compression),
  cine timing, the C-arm angles and the X-ray geometry distances. All other elements, including private
  tags, are dropped.

The files are DICOM. Cine series are multi-frame XA images; stills (only when requested) are single frames.

## Split suggestion

`train` 70%, `val` 15%, `test` 15%, taken from a hash of `patient_key`, so every case of one patient is in
the same split (no patient appears in both train and test) and repeated exports agree. A case with no patient
key is treated as its own patient (its split comes from `case_id`). With few patients, for example one, the
split is not meaningful and you should choose your own.

## What is left out

Scorer names (only the confirming scorer's level), folder labels you typed in the app, original UIDs, MRNs,
source file names and paths, and series descriptions. The study date is kept, as the project spec keeps it;
it is a quasi-identifier that the ethics review should judge. Other dates are rounded to the day.

## Burned-in text

Patient text can be burned into the pixels of an image; removing DICOM tags cannot strip it. `burned_in_unclear`
is true for series whose DICOM says so or does not say otherwise (this includes most series that do not carry
the tag at all). The README counts them. Look at those images before sharing anything.
