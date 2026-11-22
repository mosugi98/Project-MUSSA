"""Reading and writing contract documents as JSON, and the JSON Schema that describes them.

`from_json` is the one door for outside data: it refuses anything the models do not accept and explains why in
plain words, never as a traceback."""
from __future__ import annotations

import json

from pydantic import ValidationError

from .models import SCHEMA_VERSION, CaseAnalysis

MAX_PROBLEMS_SHOWN = 5


class ContractError(ValueError):
    """A contract document could not be read. The message is meant to be shown to a person."""


def to_json(analysis: CaseAnalysis, indent: int | None = None) -> str:
    return analysis.model_dump_json(indent=indent)


def _plain(error: ValidationError) -> str:
    problems = error.errors()
    lines = []
    for problem in problems[:MAX_PROBLEMS_SHOWN]:
        where = ".".join(str(part) for part in problem["loc"]) or "document"
        text = problem["msg"].removeprefix("Value error, ")
        lines.append(f"{where}: {text}")
    if len(problems) > MAX_PROBLEMS_SHOWN:
        lines.append(f"... and {len(problems) - MAX_PROBLEMS_SHOWN} more problem(s).")
    return "The analysis file has problems:\n" + "\n".join(lines)


def from_json(text: str) -> CaseAnalysis:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ContractError(f"The file is not valid JSON ({exc}).") from None
    if not isinstance(data, dict):
        raise ContractError("The file must contain one JSON object (an analysis), not a list or a single value.")
    version = data.get("schema_version")
    if version is not None and version != SCHEMA_VERSION:
        raise ContractError(f"This file uses contract version {version}, but this MUSSA reads version {SCHEMA_VERSION}. "
                            "Use a MUSSA of the matching version, or convert the file.")
    try:
        return CaseAnalysis.model_validate(data)
    except ValidationError as exc:
        raise ContractError(_plain(exc)) from None


def json_schema() -> dict:
    return CaseAnalysis.model_json_schema()


def schema_text() -> str:
    """The schema as the exact text kept in docs/contract/cag-analysis.schema.json (stable order, trailing newline)."""
    return json.dumps(json_schema(), indent=2, sort_keys=True) + "\n"
