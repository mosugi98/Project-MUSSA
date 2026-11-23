import numpy as np
import pytest
from pydantic import ValidationError

from cagsyntax.agent.perception import PerceptionError, perceive_series, perceive_study
from cagsyntax.agent.schema import RunPerceptionSummary
from cagsyntax.ai.segment_names import SEGMENT_NAMES
from cagsyntax.ai.segmenter import ModelCard, Segmenter
from cagsyntax.ai.stenosis import Candidate, StenosisFinder
from cagsyntax.dicom_import.reader import read_xa
from tests.ai.test_labels import make_store
from tests.ai.toy_models import make_toy_model, write_card


class FakeSegmenter:
    """Segment "6" fills the top half of the frame, "11" the bottom half, and "7" three stray pixels."""
    model_id = "2026-11-20 aaaa1111"

    def __init__(self):
        self.card = ModelCard("fake", "2026-11-20", 32, list(SEGMENT_NAMES), 0.5, None, "test")
        self.calls = 0

    def predict(self, frame, threshold=None):
        self.calls += 1
        h, w = frame.shape
        masks = np.zeros((25, h, w), dtype=bool)
        masks[SEGMENT_NAMES.index("6"), : h // 2] = True
        masks[SEGMENT_NAMES.index("11"), h // 2:] = True
        masks[SEGMENT_NAMES.index("7"), 0, :3] = True
        return masks


class FakeStenosis:
    """One narrowing in the top half (rows 10..19, cols 5..14), one outside any segment if asked."""
    model_id = "2026-11-21 bbbb2222"

    def __init__(self, blobs=((10, 20, 5, 15, 0.9),)):
        self.card = ModelCard("fake", "2026-11-21", 32, ["stenosis"], 0.5, None, "test")
        self.blobs, self.calls = blobs, 0

    def candidates(self, frame, threshold=None, min_pixels=30):
        self.calls += 1
        out = []
        for y0, y1, x0, x1, score in self.blobs:
            mask = np.zeros(frame.shape, dtype=bool)
            mask[y0:y1, x0:x1] = True
            out.append(Candidate(mask=mask, box=(x0, y0, x1, y1), pixels=int(mask.sum()), score=score))
        return out


@pytest.fixture
def store(tmp_path):
    return make_store(tmp_path, n=1, frames=5)


def first(store):
    return sorted(store.glob("*.dcm"))[0]


# ---------------------------------------------------------------- wiring to the DICOM reader
def test_by_default_the_middle_frame_of_the_series_is_analysed(store):
    path = first(store)
    run = perceive_series(path, FakeSegmenter(), FakeStenosis())
    assert isinstance(run, RunPerceptionSummary) and run.frame_count == 5 and run.analysed_frames == [2]
    assert {c.frame_index for c in run.candidates} == {2}


def test_the_run_carries_the_series_uid_sop_uid_angles_and_view_label_from_the_dicom(store):
    path = first(store)
    series = read_xa(path)
    run = perceive_series(path, FakeSegmenter(), FakeStenosis())
    assert run.series_instance_uid == path.stem and run.sop_instance_uid == series.sop_instance_uid
    c = run.candidates[0]
    assert (c.primary_angle_deg, c.secondary_angle_deg) == (series.primary_angle, series.secondary_angle)
    assert (c.series_instance_uid, c.sop_instance_uid) == (run.series_instance_uid, run.sop_instance_uid)
    assert run.view_label.startswith("LAO") and "CRAN" in run.view_label


def test_chosen_frames_are_all_analysed_and_listed_in_order(store):
    seg, ste = FakeSegmenter(), FakeStenosis()
    run = perceive_series(first(store), seg, ste, frames=[4, 0, 4])
    assert run.analysed_frames == [0, 4] and seg.calls == 2 and ste.calls == 2
    assert sorted({c.frame_index for c in run.candidates}) == [0, 4] and len(run.candidates) == 2


def test_a_frame_that_does_not_exist_is_refused_before_any_model_runs(store):
    seg = FakeSegmenter()
    for bad in ([9], [-1], [2, 5]):
        with pytest.raises(PerceptionError) as exc:
            perceive_series(first(store), seg, FakeStenosis(), frames=bad)
        assert "5 frames" in str(exc.value)
    assert seg.calls == 0


def test_an_empty_list_of_frames_is_refused(store):
    with pytest.raises(PerceptionError):
        perceive_series(first(store), FakeSegmenter(), FakeStenosis(), frames=[])


# ---------------------------------------------------------------- wiring to the models
def test_a_candidate_is_placed_in_its_segment_with_its_box_size_and_score(store):
    run = perceive_series(first(store), FakeSegmenter(), FakeStenosis())
    c = run.candidates[0]
    assert (c.predicted_segment, c.stenosis_score, c.segment_overlap, c.pixels) == ("6", 0.9, 1.0, 100)
    assert c.bbox_xyxy == (5, 10, 15, 20)                                         # pixel xyxy, end-exclusive


def test_nothing_the_models_cannot_measure_is_invented(store):
    c = perceive_series(first(store), FakeSegmenter(), FakeStenosis()).candidates[0]
    for name in ("qca_stenosis_percent", "reference_vessel_diameter_mm", "lesion_length_mm", "is_total_occlusion",
                 "is_bifurcation_candidate", "has_calcification_hint", "has_thrombus_hint", "image_snr_score"):
        assert getattr(c, name) is None, name
    assert perceive_series(first(store), FakeSegmenter(), FakeStenosis()).pda_origin_detected is None


def test_candidates_come_best_score_first_with_stable_unique_ids(store):
    blobs = ((10, 20, 5, 15, 0.6), (40, 50, 5, 15, 0.9))
    a = perceive_series(first(store), FakeSegmenter(), FakeStenosis(blobs))
    b = perceive_series(first(store), FakeSegmenter(), FakeStenosis(blobs))
    assert [c.stenosis_score for c in a.candidates] == [0.9, 0.6]
    ids = [c.candidate_id for c in a.candidates]
    assert len(set(ids)) == 2 and ids == [c.candidate_id for c in b.candidates]
    assert all(i.startswith(a.series_instance_uid) for i in ids)


def test_a_candidate_outside_every_segment_is_kept_as_unplaced(store):
    class NoSegments(FakeSegmenter):
        def predict(self, frame, threshold=None):
            return np.zeros((25,) + frame.shape, dtype=bool)
    run = perceive_series(first(store), NoSegments(), FakeStenosis())
    assert len(run.candidates) == 1 and run.candidates[0].predicted_segment is None
    assert run.candidates[0].segment_overlap == 0.0 and run.visible_segments == []


def test_visible_segments_are_the_ones_with_enough_pixels_in_table_order(store):
    run = perceive_series(first(store), FakeSegmenter(), FakeStenosis())
    assert run.visible_segments == ["6", "11"]                                    # "7" has 3 stray pixels only
    lenient = perceive_series(first(store), FakeSegmenter(), FakeStenosis(), min_segment_pixels=1)
    assert lenient.visible_segments == ["6", "7", "11"]


def test_a_run_with_no_candidates_still_reports_what_is_visible(store):
    run = perceive_series(first(store), FakeSegmenter(), FakeStenosis(blobs=()))
    assert run.candidates == [] and run.visible_segments == ["6", "11"]


def test_the_model_files_that_produced_the_run_are_recorded(store):
    run = perceive_series(first(store), FakeSegmenter(), FakeStenosis())
    assert [(m.name, m.identity) for m in run.models] == [("segments", "2026-11-20 aaaa1111"),
                                                          ("stenosis", "2026-11-21 bbbb2222")]


def test_missing_models_are_refused_with_the_reason(store):
    with pytest.raises(PerceptionError) as exc:
        perceive_series(first(store), None, FakeStenosis())
    assert "segment model" in str(exc.value)
    with pytest.raises(PerceptionError) as exc:
        perceive_series(first(store), FakeSegmenter(), None)
    assert "stenosis model" in str(exc.value)


def test_a_file_that_is_not_dicom_is_refused_with_a_perception_error(tmp_path):
    bad = tmp_path / "x.dcm"
    bad.write_bytes(b"not dicom")
    with pytest.raises(PerceptionError):
        perceive_series(bad, FakeSegmenter(), FakeStenosis())


def test_the_summary_survives_json(store):
    run = perceive_series(first(store), FakeSegmenter(), FakeStenosis())
    assert RunPerceptionSummary.model_validate_json(run.model_dump_json()) == run


# ---------------------------------------------------------------- the real model classes
def test_the_real_model_classes_run_end_to_end_on_a_real_dicom(tmp_path):
    store = make_store(tmp_path, n=1, frames=5)
    seg_path = make_toy_model(tmp_path / "segments.onnx", size=32, positive=(SEGMENT_NAMES.index("6"),))
    write_card(seg_path, size=32)
    ste_path = make_toy_model(tmp_path / "stenosis.onnx", size=32, channels=1, positive=(0,))
    write_card(ste_path, size=32, classes=["stenosis"])
    run = perceive_series(first(store), Segmenter.load(seg_path), StenosisFinder.load(ste_path))
    assert run.visible_segments == ["6"] and len(run.candidates) == 1
    c = run.candidates[0]
    assert (c.predicted_segment, c.segment_overlap, c.bbox_xyxy) == ("6", 1.0, (0, 0, 64, 64))
    assert [m.name for m in run.models] == ["segments", "stenosis"] and all(len(m.identity.split()[-1]) == 8 for m in run.models)


# ---------------------------------------------------------------- a whole study
def test_a_study_is_a_list_of_runs_and_one_bad_file_does_not_stop_the_rest(tmp_path):
    store = make_store(tmp_path, n=3, frames=5)
    (store / "broken.dcm").write_bytes(b"not dicom")
    paths = sorted(store.glob("*.dcm"))
    result = perceive_study(paths, FakeSegmenter(), FakeStenosis())
    assert len(result.runs) == 3 and [name for name, _ in result.skipped] == ["broken.dcm"]
    assert len({r.series_instance_uid for r in result.runs}) == 3


def test_a_study_with_nothing_readable_is_an_error(tmp_path):
    bad = tmp_path / "x.dcm"
    bad.write_bytes(b"nope")
    with pytest.raises(PerceptionError):
        perceive_study([bad], FakeSegmenter(), FakeStenosis())


def test_the_run_summary_still_refuses_unknown_fields():
    with pytest.raises(ValidationError):
        RunPerceptionSummary(series_instance_uid="1", sop_instance_uid="1", view_label="x", frame_count=1, mystery=1)


def test_a_series_whose_header_cannot_be_read_is_refused_not_trusted(store, monkeypatch):
    from cagsyntax.agent import perception
    monkeypatch.setattr(perception, "read_header", lambda p: (_ for _ in ()).throw(ValueError("bad header")))
    with pytest.raises(PerceptionError, match="header"):
        perceive_series(first(store), FakeSegmenter(), FakeStenosis())


def test_a_model_failure_on_one_series_skips_it_and_the_rest_carry_on(tmp_path):
    store = make_store(tmp_path, n=2, frames=5)
    paths = sorted(store.glob("*.dcm"))

    class FailsOnce(FakeSegmenter):
        def predict(self, frame, threshold=None):
            if self.calls == 0:
                self.calls += 1
                raise RuntimeError("model exploded")
            return super().predict(frame, threshold)
    result = perceive_study(paths, FailsOnce(), FakeStenosis())
    assert len(result.runs) == 1 and len(result.skipped) == 1 and "model exploded" in result.skipped[0][1]
