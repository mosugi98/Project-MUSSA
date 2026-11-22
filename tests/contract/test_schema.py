import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cagsyntax.contract.models import (SCHEMA_VERSION, CaseAnalysis, CaseForm, Evidence, Finding, LesionForm, ModelRef,
                                       Review, SeriesInfo)
from cagsyntax.contract.schema import ContractError, from_json, json_schema, schema_text, to_json

ROOT = Path(__file__).resolve().parents[2]
CHECKED_IN = ROOT / "docs" / "contract" / "cag-analysis.schema.json"
NOW = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)


def analysis():
    ev = Evidence(series_uid="2.25.1", frame=2, primary_angle=30.0, secondary_angle=-20.0, box=(5, 6, 20, 30))
    f = Finding(evidence=ev, segment="6", score=0.9, pixels=120, overlap=0.8,
                models=[ModelRef(name="segments", identity="2026-11-21 ab12cd34")])
    form = CaseForm(dominance="right", scoring_dominance=None, lesions=[LesionForm(segments=["6"], occlusion=False)])
    return CaseAnalysis(study_uid="2.25.9", series=[SeriesInfo(series_uid="2.25.1", kind="cine", frame_count=5, fps=15.0)],
                        findings=[f], review=Review(ai_raw_prediction=form), created_at=NOW)


# ---- JSON round trip ----
def test_an_analysis_round_trips_through_json_unchanged():
    a = analysis()
    text = to_json(a)
    assert json.loads(text)["schema_version"] == SCHEMA_VERSION
    assert from_json(text) == a


def test_the_json_is_plain_data_with_an_iso_timestamp_and_a_box_list():
    data = json.loads(to_json(analysis()))
    assert data["created_at"].startswith("2026-11-22T09:00:00") and data["findings"][0]["evidence"]["box"] == [5, 6, 20, 30]


def test_to_json_can_be_indented_for_people():
    assert "\n  " in to_json(analysis(), indent=2)


# ---- refusing bad input in plain words ----
def test_text_that_is_not_json_is_refused_plainly():
    with pytest.raises(ContractError) as exc:
        from_json("{broken")
    assert "not valid JSON" in str(exc.value) and isinstance(exc.value, ValueError)


def test_json_that_is_not_an_object_is_refused():
    with pytest.raises(ContractError) as exc:
        from_json("[1, 2]")
    assert "one JSON object" in str(exc.value)


def test_a_newer_version_is_refused_naming_both_versions():
    data = json.loads(to_json(analysis()))
    data["schema_version"] = "2.0"
    with pytest.raises(ContractError) as exc:
        from_json(json.dumps(data))
    assert "2.0" in str(exc.value) and SCHEMA_VERSION in str(exc.value)


def test_a_missing_field_is_named_by_its_path():
    data = json.loads(to_json(analysis()))
    del data["findings"][0]["evidence"]["series_uid"]
    with pytest.raises(ContractError) as exc:
        from_json(json.dumps(data))
    assert "findings.0.evidence.series_uid" in str(exc.value)


def test_an_unknown_field_is_refused():
    data = json.loads(to_json(analysis()))
    data["patient_name"] = "DOE"
    with pytest.raises(ContractError) as exc:
        from_json(json.dumps(data))
    assert "patient_name" in str(exc.value)


def test_evidence_that_points_nowhere_is_refused_with_the_reason():
    data = json.loads(to_json(analysis()))
    data["findings"][0]["evidence"]["frame"] = 9
    with pytest.raises(ContractError) as exc:
        from_json(json.dumps(data))
    assert "frame 9" in str(exc.value)


def test_many_problems_are_summarised_not_dumped():
    data = json.loads(to_json(analysis()))
    data["findings"] = [dict(data["findings"][0], score=5.0, pixels=-1, overlap=9.0) for _ in range(10)]
    with pytest.raises(ContractError) as exc:
        from_json(json.dumps(data))
    message = str(exc.value)
    assert "more" in message and len(message.splitlines()) <= 8 and "Traceback" not in message


# ---- the JSON Schema ----
def test_the_schema_describes_the_analysis_and_pins_the_version():
    schema = json_schema()
    assert schema["title"] == "CaseAnalysis" and schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    assert "Finding" in schema["$defs"] and "LesionForm" in schema["$defs"]


def test_the_schema_lists_exactly_the_25_segments_via_a_pattern_free_description():
    text = schema_text()
    assert text.endswith("\n") and json.loads(text) == json_schema()
    assert schema_text() == text                                              # deterministic


def test_the_checked_in_schema_is_in_step_with_the_models():
    assert CHECKED_IN.exists(), "run: python tools/contract/export_schema.py"
    assert CHECKED_IN.read_text(encoding="utf-8") == schema_text(), "the models changed: run tools/contract/export_schema.py"


def run_tool(*args):
    return subprocess.run([sys.executable, str(ROOT / "tools" / "contract" / "export_schema.py"), *map(str, args)],
                          capture_output=True, text=True, timeout=60)


def test_the_export_tool_writes_checks_and_notices_drift(tmp_path):
    target = tmp_path / "schema.json"
    done = run_tool("--out", target)
    assert done.returncode == 0 and target.read_text(encoding="utf-8") == schema_text()
    assert run_tool("--check", "--out", target).returncode == 0
    target.write_text("{}", encoding="utf-8")
    checked = run_tool("--check", "--out", target)
    assert checked.returncode == 1 and "out of date" in checked.stdout
    assert target.read_text(encoding="utf-8") == "{}"                          # --check never rewrites
    assert run_tool("--check", "--out", tmp_path / "missing.json").returncode == 1
