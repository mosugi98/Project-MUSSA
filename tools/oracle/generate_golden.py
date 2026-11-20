"""Generate tests/scoring/golden.json: cases plus the official calculator's totals for them.

Run after tools/oracle/fetch_official.py. Cases are accepted only if our validator calls them
complete (every question the official form would ask is answered, none it would skip). The
official totals come from the official JavaScript run in a sandbox (tools/oracle/driver.mjs).
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from cagsyntax.scoring.engine import score_case  # noqa: E402
from cagsyntax.scoring.model import Case, Lesion  # noqa: E402
from cagsyntax.scoring.tables import MEDINA, OSTIAL_SEGMENTS, SEGMENT_IDS, VERSION, weight  # noqa: E402
from cagsyntax.scoring.validate import beyond_asked, beyond_options, tri_bif_asked  # noqa: E402
from tools.oracle.oracle import run_cases  # noqa: E402

SEED = 20261120
OUT = ROOT / "tests" / "scoring" / "golden.json"


def visible(dom: str) -> list[str]:
    return [s for s in SEGMENT_IDS if weight(s, dom) is not None]


def finish_lesion(rng: random.Random, les: Lesion, dom: str) -> Lesion:
    """Answer every question the official form would ask for this lesion, at random."""
    if tri_bif_asked(les):
        les.trifurcation = rng.choice([0, 0, 0, 1, 2, 3, 4])
        if les.trifurcation == 0:
            les.bifurcation = rng.choice(["none", "none"] + list(MEDINA))
            if les.bifurcation != "none":
                les.bifurcation_angle_lt70 = rng.random() < 0.5
        else:
            les.bifurcation = "none"
    if any(s in OSTIAL_SEGMENTS for s in les.segments):
        les.aorto_ostial = rng.random() < 0.5
    les.severe_tortuosity = rng.random() < 0.3
    les.heavy_calcification = rng.random() < 0.3
    les.thrombus = rng.random() < 0.2
    if not les.occlusion:
        les.length_gt20 = rng.random() < 0.3
    return les


def occlusion_lesion(rng: random.Random, dom: str, segs: list[str], first: str,
                     beyond: str | None) -> Lesion:
    les = Lesion(segments=segs, occlusion=True, first_segment=first,
                 age_over_3_months=rng.choice(["no", "yes", "unknown"]),
                 blunt_stump=rng.random() < 0.5, bridging=rng.random() < 0.5,
                 beyond_first_visualized=beyond,
                 side_branch=rng.choice(["no", "small", "large", "both"]))
    return finish_lesion(rng, les, dom)


def random_lesion(rng: random.Random, dom: str) -> Lesion:
    vis = visible(dom)
    segs = sorted(rng.sample(vis, rng.choice([1, 1, 2, 2, 3, 4])), key=SEGMENT_IDS.index)
    if rng.random() < 0.4:
        first = rng.choice(segs)
        beyond = rng.choice(sorted(beyond_options(first, dom))) if beyond_asked(first, dom) else None
        return occlusion_lesion(rng, dom, segs, first, beyond)
    return finish_lesion(rng, Lesion(segments=segs, occlusion=False), dom)


def random_case(rng: random.Random) -> Case:
    dominance = rng.choice(["right", "left", "co-dominant"])
    scoring = rng.choice(["right", "left"]) if dominance == "co-dominant" else None
    dom = scoring or dominance
    lesions = [random_lesion(rng, dom) for _ in range(rng.choice([1, 1, 2, 3, 4, 6]))]
    diffuse = rng.sample(visible(dom), rng.choice([0, 0, 1, 2, 4]))
    return Case(dominance=dominance, scoring_dominance=scoring, lesions=lesions,
                diffuse_segments=sorted(diffuse, key=SEGMENT_IDS.index))


def systematic_cases(rng: random.Random) -> list[Case]:
    """Every occlusion main segment x every beyond-occlusion option x both dominances."""
    cases = []
    for dom in ("right", "left"):
        for main in visible(dom):
            segs = sorted({main, *rng.sample(visible(dom), 2)}, key=SEGMENT_IDS.index)
            options = sorted(beyond_options(main, dom)) if beyond_asked(main, dom) else [None]
            for beyond in options:
                les = occlusion_lesion(rng, dom, segs, main, beyond)
                cases.append(Case(dominance=dom, scoring_dominance=None, lesions=[les], diffuse_segments=[]))
    return cases


def main() -> int:
    rng = random.Random(SEED)
    cases = systematic_cases(rng)
    while len(cases) < 700:
        cases.append(random_case(rng))
    cases = [c for c in cases if score_case(c).status == "complete"]
    payload = [dataclasses.asdict(c) for c in cases]
    official = run_cases(payload)
    golden = {
        "meta": {"official_version": (ROOT / "tools/oracle/official/VERSION.txt").read_text().splitlines()[0],
                 "engine_tables_version": VERSION, "seed": SEED, "cases": len(payload),
                 "generated": datetime.date.today().isoformat()},
        "cases": [{"case": c, "official": o} for c, o in zip(payload, official)],
    }
    OUT.write_text(json.dumps(golden, indent=0), encoding="utf-8")
    print(f"wrote {len(payload)} cases to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
