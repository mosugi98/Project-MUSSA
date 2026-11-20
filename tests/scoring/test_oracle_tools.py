import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = ROOT / "tools" / "oracle" / "official" / "frameset.js"
DRIVER = ROOT / "tools" / "oracle" / "driver.mjs"

pytestmark = pytest.mark.skipif(
    not OFFICIAL.exists(),
    reason="official calculator files not downloaded; run python tools/oracle/fetch_official.py")


def base_lesion(**kw):
    d = dict(segments=["6"], occlusion=False, first_segment=None, age_over_3_months=None,
             blunt_stump=None, bridging=None, beyond_first_visualized=None, side_branch=None,
             trifurcation=0, bifurcation="none", bifurcation_angle_lt70=None, aorto_ostial=False,
             severe_tortuosity=False, length_gt20=False, heavy_calcification=False, thrombus=False)
    d.update(kw)
    return d


def test_driver_scores_a_known_case():
    from tools.oracle.oracle import run_cases
    case = dict(dominance="right", scoring_dominance=None, lesions=[base_lesion()], diffuse_segments=[])
    [res] = run_cases([case])
    assert res["total"] == 7 and res["per_lesion"] == [7] and res["diffuse"] == 0


def test_driver_scores_occlusion_and_diffuse():
    from tools.oracle.oracle import run_cases
    occ = base_lesion(segments=["2", "3"], occlusion=True, first_segment="2", age_over_3_months="yes",
                      blunt_stump=True, bridging=False, beyond_first_visualized="3", side_branch="small",
                      trifurcation=None, bifurcation=None, aorto_ostial=None, length_gt20=None)
    case = dict(dominance="right", scoring_dominance=None, lesions=[occ], diffuse_segments=["7", "8"])
    [res] = run_cases([case])
    # (1*5 + 1*2) + age 1 + blunt 1 + beyond "3" 0 + side branch small 1 = 10, diffuse +2
    assert res["per_lesion"] == [10] and res["diffuse"] == 2 and res["total"] == 12


def test_driver_sandbox_exposes_no_filesystem_process_or_network():
    out = subprocess.run(["node", str(DRIVER), "--selftest-sandbox"], capture_output=True, text=True,
                         timeout=60, cwd=ROOT)
    info = json.loads(out.stdout)
    assert info == {"require": "undefined", "process": "undefined", "fetch": "undefined",
                    "XMLHttpRequest": "undefined"}
