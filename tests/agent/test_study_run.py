import json

import pydicom
import pytest

from cagsyntax.agent.reconcile import ReconcileError
from cagsyntax.agent.study_run import StudyRun, lesions_for_form, run_study, study_paths
from cagsyntax.dicom_import.reader import read_header
from cagsyntax.library import Library
from cagsyntax.scoring import Lesion
from tests.agent.test_perception import FakeSegmenter, FakeStenosis
from tests.agent.test_reconcile import store_of_one_study

def library_of(tmp_path, runs=2):
    store = store_of_one_study(tmp_path, runs=runs)
    paths = sorted(store.glob("*.dcm"))
    return Library(tmp_path), paths, read_header(paths[0]).study_uid      # the importer remaps the study uid


def test_only_the_series_of_the_asked_study_are_returned_in_a_stable_order(tmp_path):
    lib, paths, study = library_of(tmp_path, runs=3)
    other = pydicom.dcmread(paths[2])
    other.StudyInstanceUID = "1.2.3.99"
    other.save_as(paths[2])
    got = study_paths(lib, study)
    assert got == paths[:2] and study_paths(lib, "1.2.3.99") == [paths[2]] and study_paths(lib, "9.9") == []


def test_a_study_run_proposes_draft_lessons_with_the_evidence_to_jump_to(tmp_path):
    lib, paths, study = library_of(tmp_path)
    run = run_study(paths, FakeSegmenter(), FakeStenosis(), study)
    assert isinstance(run, StudyRun) and run.skipped == [] and len(run.runs) == 2
    study = run.reconciliation.study
    assert study.study_instance_uid == read_header(paths[0]).study_uid
    assert [(les.lesion_id, les.draft) for les in study.lesions] == [("AI_6", True)]
    series, frame = run.evidence_of("AI_6")
    assert series in {p.stem for p in paths} and frame == 2


def test_a_study_given_that_contradicts_the_files_is_refused_so_patients_are_never_mixed(tmp_path):
    _lib, paths, study = library_of(tmp_path)
    with pytest.raises(ReconcileError):
        run_study(paths, FakeSegmenter(), FakeStenosis(), "1.2.3.99")


def test_an_unreadable_file_is_listed_and_the_rest_carry_on(tmp_path):
    _lib, paths, study = library_of(tmp_path)
    bad = tmp_path / "broken.dcm"
    bad.write_bytes(b"not dicom")
    run = run_study([bad] + paths, FakeSegmenter(), FakeStenosis(), study)
    assert [n for n, _ in run.skipped] == ["broken.dcm"] and len(run.runs) == 2


def test_the_raw_payload_keeps_every_run_and_the_proposal_and_the_models(tmp_path):
    _lib, paths, study = library_of(tmp_path)
    run = run_study(paths, FakeSegmenter(), FakeStenosis(), study)
    data = json.loads(run.payload_json())
    assert len(data["runs"]) == 2 and data["reconciliation"]["study"]["lesions"][0]["lesion_id"] == "AI_6"
    assert run.model_ids() == ("segments 2026-11-20 aaaa1111", "stenosis 2026-11-21 bbbb2222")
    assert run.proposed_ids() == ["AI_6"]


def test_chosen_lessons_become_segment_only_form_lesions_in_the_proposed_order(tmp_path):
    _lib, paths, study = library_of(tmp_path)
    run = run_study(paths, FakeSegmenter(), FakeStenosis(blobs=((10, 20, 5, 15, 0.9), (40, 50, 5, 15, 0.7))), study)
    assert run.proposed_ids() == ["AI_6", "AI_11"]
    assert lesions_for_form(run, ["AI_11", "AI_6"]) == [Lesion(segments=["6"]), Lesion(segments=["11"])]
    assert lesions_for_form(run, []) == []
    with pytest.raises(KeyError):
        lesions_for_form(run, ["AI_99"])


def test_a_series_with_the_same_study_uid_but_another_patient_is_left_out(tmp_path):
    lib, paths, study = library_of(tmp_path, runs=2)
    mrn = read_header(paths[0]).mrn_hash
    other = pydicom.dcmread(paths[1])
    other.PatientID = "someone-else"
    other.save_as(paths[1])
    assert study_paths(lib, study, mrn) == [paths[0]] and study_paths(lib, study) == paths
