import dataclasses
import json
from pathlib import Path

from cagsyntax.scoring.engine import score_case
from cagsyntax.scoring.model import Case, Lesion

GOLDEN = Path(__file__).parent / "golden.json"
DATA = json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_case_from_dict_roundtrip():
    entry = DATA["cases"][0]["case"]
    case = Case.from_dict(entry)
    assert isinstance(case.lesions[0], Lesion)
    assert dataclasses.asdict(case) == entry


def test_golden_set_is_large_and_varied():
    cases = [e["case"] for e in DATA["cases"]]
    assert len(cases) >= 500
    assert {c["dominance"] for c in cases} == {"right", "left", "co-dominant"}
    lesions = [l for c in cases for l in c["lesions"]]
    assert sum(l["occlusion"] for l in lesions) >= 200
    assert any(l["trifurcation"] for l in lesions) and any(l["bifurcation"] not in (None, "none") for l in lesions)
    assert any(c["diffuse_segments"] for c in cases)
    assert "2.28" in DATA["meta"]["official_version"]


def test_engine_matches_the_official_calculator_on_every_golden_case():
    mismatches = []
    for i, entry in enumerate(DATA["cases"]):
        result = score_case(Case.from_dict(entry["case"]))
        official = entry["official"]
        ours = (result.status, result.total, [l.total for l in result.lesions], result.diffuse_points)
        theirs = ("complete", official["total"], official["per_lesion"], official["diffuse"])
        if ours != theirs:
            mismatches.append((i, ours, theirs, entry["case"]))
    assert not mismatches, (
        f"{len(mismatches)} of {len(DATA['cases'])} golden cases differ. First 3 (index, ours, official, case):\n"
        + "\n".join(str(m) for m in mismatches[:3]))
