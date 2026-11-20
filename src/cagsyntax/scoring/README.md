# SYNTAX scoring engine

A pure function from a case to a score. No UI, no AI, no I/O.

```python
from cagsyntax.scoring import Case, Lesion, score_case

case = Case(dominance="right", scoring_dominance=None, lesions=[
    Lesion(segments=["6"], occlusion=False, trifurcation=0, bifurcation="none",
           aorto_ostial=False, severe_tortuosity=False, length_gt20=False,
           heavy_calcification=False, thrombus=False)])
result = score_case(case)
result.status    # "complete"
result.total     # 7.0   (LAD proximal, weight 3.5 x 2)
result.group     # "low"
result.lesions[0].parts   # [Part("Segments (...)", 7.0)]
```

## Status

| `status` | Meaning | `total` / `group` |
|---|---|---|
| `complete` | every applicable question answered, no impossible combinations | set |
| `incomplete` | something required is missing (no dominance, no lesions, an unanswered question) | `None` |
| `invalid` | an impossible combination (for example segment 15 under right dominance) | `None` |

`result.issues` lists each problem with a code (for example `segment_not_applicable`) and the
lesion index. Invalid wins over incomplete. Fields left as `None` mean "not answered"; a
question the official form would skip (for example trifurcation after an occlusion with a small
side branch) must be `None` and is an error if filled in.

## Source and checking

- Tables: official calculator v2.28 (`tables.py` records the source URL and version).
- The engine matches the official calculator's own code on every case in
  `tests/scoring/golden.json` (700 cases). Quirks of the official code that were not copied are in
  `tests/scoring/KNOWN_OFFICIAL_QUIRKS.md`.
- To regenerate the golden file: `python tools/oracle/fetch_official.py`, then
  `python tools/oracle/generate_golden.py`. This downloads the official files into
  `tools/oracle/official/` (git-ignored) and runs them in a Node sandbox with no file or network
  access. The official code is never committed or shipped; only the resulting numbers are.

Educational and research use. Not a certified medical device.
