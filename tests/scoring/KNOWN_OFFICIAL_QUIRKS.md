# Known quirks in the official calculator (v2.28) that the engine does not copy

The engine matches the official calculator on all 700 golden cases (`golden.json`). These are
places where the official page code behaves oddly, found while reading `frameset.js` and
`form.js`. None of them changes a score for a case the real form can produce, so the golden
cases avoid them; the engine follows the intended rule.

| Official behaviour | Where | What the engine does |
|---|---|---|
| Re-selecting the same bifurcation type removes its points (`SetBifurcation` only sets a score when the value changes) | `frameset.js` ~1867 | Each answer is applied once; the points always follow the answer. |
| `meAortoOstialLesion[i]==-1;` is a comparison, not an assignment, in `reset()` and `resetAnswersForLesion()` | `frameset.js` ~1334 | No effect on scores; the driver always sets the answer explicitly. |
| `if (meTotalOcclusion==1) CalculationFactor=5;` is overwritten inside the loop | `frameset.js` ~1508 | Only the marked first segment gets x5; all others x2 (the effective official rule). |
| `setVisualizedByMainSegment` is defined twice; `getForcedTrifurcationAnswer()` returns false before its checks | `frameset.js` ~1655, ~1975 | Not relevant to scoring. |
| `meSegmentsInvolved` is not cleared by `reset()` | `frameset.js` ~1301 | The driver uses a fresh sandbox per case. |
| The side-branch comment says option 2 scores 0, but every non-"No" answer scores 1 | `frameset.js` ~1825 | Every non-"No" answer scores 1 (the code, not the comment). |
| The "first segment beyond the occlusion" button passes the main segment unquoted (`Question4V('7', 9a)`), which is invalid JavaScript for segments like 9a | `form.js` ~411 | Those segments have one candidate, so the question is never shown and scores 0. |

## What the golden generator does not cover

- Only questions the official form would actually ask are answered. Combinations the form
  cannot reach (for example a bifurcation after an occlusion with a side branch under 1.5 mm)
  are rejected by the validator and are not in the golden set.
- Free-text comments and the score overview pages are not part of the score.
- SYNTAX Score II is out of scope.
