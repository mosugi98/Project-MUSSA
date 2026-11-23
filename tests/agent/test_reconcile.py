import random

import pytest

from cagsyntax.agent.adapters import score_study
from cagsyntax.agent.perception import perceive_study
from cagsyntax.agent.reconcile import DeterministicReconciler, ReconcileError, Reconciliation, reconcile
from cagsyntax.agent.schema import RawCVLesionCandidate, RunPerceptionSummary
from cagsyntax.dicom_import.reader import read_header
from tests.agent.test_perception import FakeSegmenter, FakeStenosis
from tests.ai.test_labels import make_store

STUDY = "2.25.9"


def cand(series="2.25.1", frame=10, segment="8", score=0.9, overlap=0.9, box=(10, 10, 30, 40), rank=0, angles=(30.0, 20.0)):
    return RawCVLesionCandidate(candidate_id=f"{series}:f{frame}:c{rank}", predicted_segment=segment, stenosis_score=score,
                                segment_overlap=overlap, series_instance_uid=series, sop_instance_uid=series + ".1",
                                frame_index=frame, primary_angle_deg=angles[0], secondary_angle_deg=angles[1],
                                bbox_xyxy=box, pixels=300)


def run(series="2.25.1", candidates=(), label="LAO 30 CRAN 20", study=STUDY, pda=None, visible=()):
    return RunPerceptionSummary(series_instance_uid=series, sop_instance_uid=series + ".1", view_label=label,
                                frame_count=40, analysed_frames=[10], visible_segments=list(visible),
                                candidates=list(candidates), pda_origin_detected=pda, study_instance_uid=study)


def lesions(result):
    return {les.lesion_id: les for les in result.study.lesions}


# ---------------------------------------------------------------- merging views
def test_the_same_segment_seen_in_two_runs_becomes_one_draft_lesion_with_one_primary_view():
    a = run("2.25.1", [cand("2.25.1", segment="8", score=0.7)], label="LAO 30 CRAN 20")
    b = run("2.25.2", [cand("2.25.2", segment="8", score=0.92)], label="RAO 20 CAUD 10")
    result = reconcile([a, b], dominance="right")
    assert list(lesions(result)) == ["AI_8"]
    les = result.study.lesions[0]
    assert les.draft is True and [s.segment_id for s in les.involved_segments] == ["8"]
    assert les.primary_evidence.series_instance_uid == "2.25.2" and les.primary_evidence.confidence_score == 0.92
    assert [v.series_instance_uid for v in les.supporting_views] == ["2.25.1"]


def test_the_view_label_of_every_run_is_kept_so_a_person_can_be_told_which_view():
    a = run("2.25.1", [cand("2.25.1")], label="LAO 30 CRAN 20")
    b = run("2.25.2", [], label="RAO 20 CAUD 10")
    assert reconcile([a, b]).view_labels == {"2.25.1": "LAO 30 CRAN 20", "2.25.2": "RAO 20 CAUD 10"}


def test_different_segments_become_different_lesions_in_table_order():
    r = run(candidates=[cand(segment="11", rank=0), cand(segment="6", rank=1), cand(segment="8", rank=2)])
    assert [les.lesion_id for les in reconcile([r]).study.lesions] == ["AI_6", "AI_8", "AI_11"]


def test_the_primary_view_is_the_highest_score_then_the_best_placed_then_the_larger_candidate():
    best = cand("2.25.1", score=0.9, overlap=0.95)
    worse_placement = cand("2.25.2", score=0.9, overlap=0.6)
    assert reconcile([run("2.25.2", [worse_placement]), run("2.25.1", [best])]).study.lesions[0].primary_evidence \
        .series_instance_uid == "2.25.1"


def test_a_lesion_seen_in_one_view_has_a_primary_view_and_no_supporting_views():
    les = reconcile([run(candidates=[cand()])]).study.lesions[0]
    assert les.primary_evidence is not None and les.supporting_views == []
    assert "1 view" in les.agent_reasoning


def test_the_evidence_carries_series_sop_frame_angles_and_the_pixel_box():
    e = reconcile([run(candidates=[cand(frame=12, box=(10, 20, 30, 50), angles=(-26.8, 17.7))])]).study.lesions[0].primary_evidence
    assert (e.series_instance_uid, e.sop_instance_uid, e.frame_index) == ("2.25.1", "2.25.1.1", 12)
    assert (e.primary_angle_deg, e.secondary_angle_deg, e.bbox_xyxy) == (-26.8, 17.7, (10, 20, 30, 50))
    assert e.qca_stenosis_percent is None and e.reference_vessel_diameter_mm is None


# ---------------------------------------------------------------- nothing is lost, nothing is decided for the scorer
def test_candidates_outside_every_segment_are_reported_not_dropped_and_not_made_lesions():
    r = run(candidates=[cand(segment=None, overlap=0.0, rank=0), cand(segment="8", rank=1)])
    result = reconcile([r])
    assert [c.candidate_id for c in result.unplaced] == ["2.25.1:f10:c0"] and len(result.study.lesions) == 1
    assert any("outside" in w for w in result.warnings)


def test_no_candidates_gives_an_empty_study_and_says_so():
    result = reconcile([run(candidates=[])])
    assert result.study.lesions == [] and any("no narrowing" in w.lower() for w in result.warnings)


def test_the_lesions_are_drafts_so_the_score_stays_incomplete_until_the_scorer_answers():
    out = score_study(reconcile([run(candidates=[cand(segment="6")])], dominance="right").study)
    assert out.status == "incomplete" and out.total_syntax_score is None and out.requires_physician_attention is True


def test_dominance_is_only_set_when_the_runs_agree_or_the_caller_says_so():
    assert reconcile([run(pda="right")]).study.dominance == "right"
    assert reconcile([run("2.25.1", pda="left"), run("2.25.2", pda="left")]).study.dominance == "left"
    assert reconcile([run()], dominance="co-dominant").study.dominance == "co-dominant"
    undecided = reconcile([run("2.25.1", pda="left"), run("2.25.2", pda="right")])
    assert undecided.study.dominance is None and any("dominance" in w.lower() for w in undecided.warnings)
    assert reconcile([run()]).study.dominance is None
    assert score_study(reconcile([run(candidates=[cand()])]).study).status == "incomplete"


# ---------------------------------------------------------------- flagging for the physician
def attention(*candidates, runs=None):
    result = reconcile(runs or [run(candidates=list(candidates))])
    return {les.lesion_id: les.primary_evidence.needs_attention for les in result.study.lesions}


def test_a_confident_well_placed_lesion_outside_the_busy_bifurcations_is_not_flagged():
    assert attention(cand(segment="8", score=0.95, overlap=0.9)) == {"AI_8": False}


def test_low_score_poor_placement_and_overlap_prone_segments_are_flagged():
    assert attention(cand(segment="8", score=0.6)) == {"AI_8": True}                  # score under 0.80
    assert attention(cand(segment="8", score=0.95, overlap=0.4)) == {"AI_8": True}    # only partly inside the segment
    for busy in ("5", "6", "11"):                                                     # LM, proximal LAD, proximal LCx
        assert attention(cand(segment=busy, score=0.95)) == {f"AI_{busy}": True}


def test_views_that_disagree_strongly_are_flagged_and_the_reason_is_written_down():
    a = run("2.25.1", [cand("2.25.1", segment="8", score=0.95)])
    b = run("2.25.2", [cand("2.25.2", segment="8", score=0.55)])
    les = reconcile([a, b]).study.lesions[0]
    assert les.primary_evidence.needs_attention is True and "disagree" in les.agent_reasoning.lower()


def test_two_separate_narrowings_in_one_segment_of_one_frame_are_flagged_as_a_possible_second_lesion():
    far = run(candidates=[cand(rank=0, box=(10, 10, 30, 30)), cand(rank=1, box=(100, 100, 120, 120))])
    result = reconcile([far])
    assert len(result.study.lesions) == 1 and result.study.lesions[0].primary_evidence.needs_attention is True
    assert any("second lesion" in w for w in result.warnings)
    near = run(candidates=[cand(rank=0, box=(10, 10, 30, 30)), cand(rank=1, box=(20, 20, 40, 40))])
    assert not any("second lesion" in w for w in reconcile([near]).warnings)


def test_the_reasoning_names_the_views_and_the_model_score_and_never_a_syntax_number():
    a = run("2.25.1", [cand("2.25.1", segment="8", score=0.7)], label="LAO 30 CRAN 20")
    b = run("2.25.2", [cand("2.25.2", segment="8", score=0.92)], label="RAO 20 CAUD 10")
    text = reconcile([a, b]).study.lesions[0].agent_reasoning
    assert "RAO 20 CAUD 10" in text and "LAO 30 CRAN 20" in text and "model score" in text and "2 views" in text
    assert "points" not in text.lower() and "syntax score" not in text.lower()


# ---------------------------------------------------------------- safety
def test_runs_from_two_different_studies_are_refused():
    with pytest.raises(ReconcileError) as exc:
        reconcile([run("2.25.1", study="2.25.9"), run("2.25.2", study="2.25.8")])
    assert "different studies" in str(exc.value)


def test_the_study_uid_comes_from_the_runs_or_the_caller_and_must_exist():
    assert reconcile([run(study="2.25.9")]).study.study_instance_uid == "2.25.9"
    assert reconcile([run(study=None)], study_instance_uid="2.25.7").study.study_instance_uid == "2.25.7"
    with pytest.raises(ReconcileError):
        reconcile([run(study=None)])
    with pytest.raises(ReconcileError):
        reconcile([run(study="2.25.9")], study_instance_uid="2.25.7")                 # the caller contradicts the runs


def test_no_runs_is_an_error():
    with pytest.raises(ReconcileError):
        reconcile([])


def test_the_result_does_not_depend_on_the_order_of_the_runs_or_candidates():
    cands = [cand("2.25.1", segment="8", rank=0, score=0.8), cand("2.25.1", segment="6", rank=1, score=0.9)]
    runs = [run("2.25.1", cands), run("2.25.2", [cand("2.25.2", segment="8", score=0.85)]),
            run("2.25.3", [cand("2.25.3", segment="11", score=0.7)])]
    expected = reconcile(runs, dominance="right").model_dump_json()
    for seed in range(6):
        shuffled = [r.model_copy(update={"candidates": random.Random(seed).sample(r.candidates, len(r.candidates))})
                    for r in random.Random(seed).sample(runs, len(runs))]
        assert reconcile(shuffled, dominance="right").model_dump_json() == expected


def test_a_duplicate_candidate_is_counted_once():
    c = cand()
    les = reconcile([run(candidates=[c, c])]).study.lesions[0]
    assert les.supporting_views == []


def test_the_result_survives_json_and_the_reconciler_object_gives_the_same_answer():
    runs = [run(candidates=[cand(segment="8"), cand(segment=None, overlap=0.0, rank=1)])]
    result = reconcile(runs, dominance="left")
    assert Reconciliation.model_validate_json(result.model_dump_json()) == result
    assert DeterministicReconciler().reconcile(runs, dominance="left") == result


# ---------------------------------------------------------------- the whole chain on real DICOM files
SALT = b"s" * 32


def store_of_one_study(tmp_path, runs=2):
    """`runs` series that really belong to one study (the test factory gives every file its own study)."""
    import pydicom
    from cagsyntax.dicom_import.importer import import_path
    from tests.dicom_factory import make_xa
    src = tmp_path / "in"
    src.mkdir()
    for k in range(runs):
        p = make_xa(src / f"r{k}.dcm", frames=5, primary=30.0 + 10 * k)
        ds = pydicom.dcmread(p)
        ds.StudyInstanceUID = "1.2.3.77"
        ds.save_as(p)
    store = tmp_path / "store"
    import_path(src, store, SALT)
    return store


def test_perception_then_reconciliation_then_the_engine_on_real_files(tmp_path):
    paths = sorted(store_of_one_study(tmp_path, runs=2).glob("*.dcm"))
    perception = perceive_study(paths, FakeSegmenter(), FakeStenosis())
    assert {r.study_instance_uid for r in perception.runs} == {read_header(paths[0]).study_uid}
    assert len({r.series_instance_uid for r in perception.runs}) == 2
    result = reconcile(perception.runs, dominance="right")
    assert [les.lesion_id for les in result.study.lesions] == ["AI_6"]
    les = result.study.lesions[0]
    assert len(les.supporting_views) == 1 and les.primary_evidence.bbox_xyxy == (5, 10, 15, 20)
    out = score_study(result.study)
    assert out.status == "incomplete" and out.total_syntax_score is None


def test_files_of_two_different_studies_are_refused_end_to_end(tmp_path):
    store = make_store(tmp_path, n=2, frames=5)                   # the factory gives each file its own study
    perception = perceive_study(sorted(store.glob("*.dcm")), FakeSegmenter(), FakeStenosis())
    assert len({r.study_instance_uid for r in perception.runs}) == 2
    with pytest.raises(ReconcileError) as exc:
        reconcile(perception.runs)
    assert "different studies" in str(exc.value)


def test_a_run_records_the_study_it_came_from(tmp_path):
    path = sorted(store_of_one_study(tmp_path, runs=1).glob("*.dcm"))[0]
    run = perceive_study([path], FakeSegmenter(), FakeStenosis()).runs[0]
    assert run.study_instance_uid == read_header(path).study_uid and run.study_instance_uid.startswith("2.25.")
