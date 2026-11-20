"""Download the official SYNTAX calculator files into tools/oracle/official/ (git-ignored).

The official code is used only locally, to generate golden test numbers. It is never committed
or shipped. This script is the only place that touches the network.
"""
from __future__ import annotations

import datetime
import re
import sys
import urllib.request
from pathlib import Path

BASE = "https://syntaxscore.org/calculator/syntaxscore/"
FILES = ["javascript/frameset.js", "javascript/form.js", "javascript/version.js",
         "form.htm", "lesion_segments.htm"]
OUT = Path(__file__).resolve().parent / "official"


def fetch(rel: str) -> bytes:
    req = urllib.request.Request(BASE + rel, headers={"User-Agent": "python-urllib"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        if resp.status != 200:
            raise RuntimeError(f"{rel}: HTTP {resp.status}")
        return resp.read()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for rel in FILES:
        data = fetch(rel)
        target = OUT / Path(rel).name
        target.write_bytes(data)
        print(f"ok  {rel} ({len(data)} bytes)")
    version_js = (OUT / "version.js").read_text(encoding="latin-1")
    match = re.search(r"(\d+\.\d+)", version_js)
    version = match.group(1) if match else "unknown"
    (OUT / "VERSION.txt").write_text(
        f"official calculator version {version}\ndownloaded {datetime.date.today().isoformat()}\n"
        f"source {BASE}\n", encoding="utf-8")
    print("version:", version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
