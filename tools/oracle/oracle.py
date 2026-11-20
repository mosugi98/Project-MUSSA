"""Run cases through the official calculator's JavaScript (sandboxed, via tools/oracle/driver.mjs)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

DRIVER = Path(__file__).resolve().parent / "driver.mjs"


def run_cases(cases: list[dict]) -> list[dict]:
    """Return the official {total, per_lesion, diffuse} for each case dict, in order."""
    proc = subprocess.run(["node", str(DRIVER)], input=json.dumps(cases), capture_output=True,
                          text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"oracle driver failed: {proc.stderr.strip()[:500]}")
    results = json.loads(proc.stdout)
    for i, r in enumerate(results):
        if "error" in r:
            raise RuntimeError(f"oracle error on case {i}: {r['error']}")
    return results
