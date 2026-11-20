# MUSSA dataset export: format

Produced by **Export dataset** in the app (spec step 4). Educational and research use; not a
certified medical device. Everything is de-identified: see "What is left out".

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
| `created` | UTC time of the export |
| `engine` | `source` (URL of the official calculator code the engine was checked against) and `version` |
| `options` | `include_stills`, `images_copied` |
| `notice` | the research / not-a-medical-device notice |
| `counts` | `cases`, `series`, `excluded`, `inconsistent` |
| `cases` | list, see below |
| `excluded` | confirmed cases that could not be exported: `case_id`, `reason` |

Each entry of `cases`:

| Key | Meaning |
|---|---|
| `case_id` | the study, as a remapped (anonymous) study UID |
| `patient_key` | salted hash of the MRN: all cases of one patient share it |
| `suggested_split` | `train`, `val` or `test` (see "Split suggestion") |
| `confirmed_at`, `confirmed_by_level` | when the reference was confirmed and the confirmer's level (never a name) |
| `reference` | the confirmed snapshot (see below) |
| `rescored` | the current engine on the same form: `total`, `group`, `consistent` |
| `series` | list: `series_id`, `kind` (`cine` or `still`), `view` (e.g. "RAO 27 CRAN 18"), `frames`, `study_date`, `path`, and `sha256` when images are copied |

`reference`: `total`, `group` (low / intermediate / high), `dominance` (right / left / co-dominant),
`scoring_dominance` (the table used), `lesions` (each with `segments`, `total` and `parts`, the labelled
points that add up to the lesion total), `diffuse_segments`, and `form`, the raw form data exactly as
confirmed (usable to rebuild the case).

`consistent` is false when the current engine's total or group differs from the confirmed one (for
example after an engine update). The case is still exported with the reference as confirmed, and
`README.txt` carries a warning.

## cases.csv and series.csv

`cases.csv` columns: `case_id, patient_key, suggested_split, reference_total, reference_group, dominance,
scoring_dominance, n_lesions, n_series, n_cines, consistent_with_engine`.

`series.csv` columns: `case_id, series_id, kind, view, frames, path`. Join the two files on `case_id`.

## Reading a series

- Without copied images, `path` is relative to the app's data folder (`C:\Users\<you>\MUSSA-data`),
  for example `store/2.25.<digits>.dcm`. Moving or deleting that folder breaks the paths.
- With copied images, `path` is `images/<series_id>.dcm` inside the export and `sha256` lets you
  check each file.

The files are de-identified DICOM. Cine series are multi-frame XA images; stills (only when requested)
are single frames.

## Split suggestion

`train` 70%, `val` 15%, `test` 15%, taken from a hash of `patient_key`, so every case of one patient is in
the same split (no patient appears in both train and test) and repeated exports agree. With few patients,
for example one, the split is not meaningful and you should choose your own.

## What is left out

Scorer names (only the confirming scorer's level), folder labels you typed in the app, original UIDs,
MRNs, source file names and paths, and series descriptions. The study date is kept, as the project spec
keeps it; it is a quasi-identifier that the ethics review should judge.
