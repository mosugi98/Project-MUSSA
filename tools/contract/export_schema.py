"""Write (or check) the JSON Schema of the MUSSA data contract.

    python tools/contract/export_schema.py            # rewrite docs/contract/cag-analysis.schema.json
    python tools/contract/export_schema.py --check    # exit 1 if the file is out of date (changes nothing)

Run it after changing anything in src/cagsyntax/contract/models.py; a test fails while the file is stale."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cagsyntax.contract.schema import schema_text  # noqa: E402

DEFAULT_OUT = ROOT / "docs" / "contract" / "cag-analysis.schema.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the MUSSA data contract as a JSON Schema.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="schema file (default: docs/contract/...)")
    parser.add_argument("--check", action="store_true", help="only check that the file is up to date")
    args = parser.parse_args(argv)
    wanted = schema_text()
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else None
        if current == wanted:
            print(f"{args.out} is up to date.")
            return 0
        print(f"{args.out} is out of date: run python tools/contract/export_schema.py")
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(wanted, encoding="utf-8")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
