import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from cagsyntax.agent.arcade_labels import (ARCADE_CATEGORIES, STENOSIS_CATEGORY_ID, segment_for_category,
                                           xyxy_from_coco_bbox, xyxy_from_mask)
from cagsyntax.agent.schema import RawCVLesionCandidate, RunPerceptionSummary
from cagsyntax.ai.segment_names import SEGMENT_NAMES

ROOT = Path(__file__).resolve().parents[2]


def candidate(**kw):
    base = dict(candidate_id="c1", predicted_segment="6", stenosis_score=0.9, segment_overlap=0.8,
                series_instance_uid="2.25.1", sop_instance_uid="2.25.1.1", frame_index=12, pixels=480,
                primary_angle_deg=30.0, secondary_angle_deg=-20.0, bbox_xyxy=(100, 120, 140, 180))
    base.update(kw)
    return RawCVLesionCandidate(**base)


# ---------------------------------------------------------------- the candidate
def test_a_candidate_needs_only_what_the_models_produce():
    c = candidate(primary_angle_deg=None, secondary_angle_deg=None, bbox_xyxy=None)
    assert c.qca_stenosis_percent is None and c.reference_vessel_diameter_mm is None and c.lesion_length_mm is None
    assert c.is_total_occlusion is None and c.has_calcification_hint is None and c.image_snr_score is None


def test_an_unplaced_candidate_is_allowed():
    assert candidate(predicted_segment=None, segment_overlap=0.0).predicted_segment is None


def test_a_candidate_checks_ranges_boxes_and_segment_names():
    for bad in (dict(stenosis_score=1.2), dict(segment_overlap=-0.1), dict(frame_index=-1), dict(pixels=-5),
                dict(predicted_segment="LAD"), dict(bbox_xyxy=(5, 5, 5, 9)), dict(bbox_xyxy=(-1, 0, 4, 4)),
                dict(qca_stenosis_percent=120.0), dict(reference_vessel_diameter_mm=0.0), dict(image_snr_score=2.0),
                dict(candidate_id=""), dict(primary_angle_deg=999.0)):
        with pytest.raises(ValidationError):
            candidate(**bad)


def test_a_candidate_refuses_unknown_fields():
    with pytest.raises(ValidationError):
        candidate(patient_name="DOE")


# ---------------------------------------------------------------- the run summary
def test_a_run_summary_round_trips_through_json():
    run = RunPerceptionSummary(series_instance_uid="2.25.1", sop_instance_uid="2.25.1.1", view_label="LAO 30 / CRAN 20",
                               frame_count=60, analysed_frames=[30], visible_segments=["5", "6", "7"],
                               candidates=[candidate()])
    again = RunPerceptionSummary.model_validate_json(run.model_dump_json())
    assert again == run and again.pda_origin_detected is None


def test_a_run_summary_checks_its_segments_and_frame_count():
    base = dict(series_instance_uid="2.25.1", sop_instance_uid="2.25.1.1", view_label="x", frame_count=10)
    assert RunPerceptionSummary(**base).candidates == []
    for bad in (dict(frame_count=0), dict(visible_segments=["99"]), dict(pda_origin_detected="both")):
        with pytest.raises(ValidationError):
            RunPerceptionSummary(**{**base, **bad})


# ---------------------------------------------------------------- the annotation dataset (ARCADE)
def test_every_arcade_segment_category_is_one_of_our_25_names_and_each_is_covered_once():
    names = [name for _id, name in ARCADE_CATEGORIES if name != "stenosis"]
    assert sorted(names) == sorted(SEGMENT_NAMES) and len(names) == 25
    assert ARCADE_CATEGORIES[-1] == (STENOSIS_CATEGORY_ID, "stenosis") and STENOSIS_CATEGORY_ID == 26


def test_categories_are_matched_by_name_not_by_position():
    assert segment_for_category("9a") == "9a" and segment_for_category("stenosis") is None
    assert segment_for_category(" 9A ") == "9a"                                    # CVAT-style typos are tolerated
    with pytest.raises(ValueError):
        segment_for_category("LAD")


def test_the_arcade_id_table_matches_the_real_annotation_files_when_the_dataset_is_present():
    path = ROOT / "arcade" / "arcade" / "stenosis" / "val" / "annotations" / "val.json"
    if not path.exists():
        pytest.skip("the ARCADE dataset is not on this PC")
    real = [(c["id"], c["name"]) for c in json.loads(path.read_text(encoding="utf-8"))["categories"]]
    assert real == ARCADE_CATEGORIES


# ---------------------------------------------------------------- coordinates
def test_a_coco_bbox_x_y_w_h_in_pixels_becomes_an_integer_xyxy_box_that_contains_it():
    assert xyxy_from_coco_bbox([229.53, 230.42, 39.52, 55.86]) == (229, 230, 270, 287)   # a real ARCADE bbox
    assert xyxy_from_coco_bbox([10, 20, 5, 5]) == (10, 20, 15, 25)


def test_a_coco_bbox_is_clipped_to_the_image_and_degenerate_boxes_are_refused():
    assert xyxy_from_coco_bbox([500, 500, 40, 40], image_size=(512, 512)) == (500, 500, 512, 512)
    assert xyxy_from_coco_bbox([-5, -5, 20, 20], image_size=(512, 512)) == (0, 0, 15, 15)
    for bad in ([10, 10, 0, 5], [600, 10, 5, 5], [1, 2, 3]):
        with pytest.raises(ValueError):
            xyxy_from_coco_bbox(bad, image_size=(512, 512))


def test_a_mask_gives_its_tight_end_exclusive_box():
    mask = np.zeros((40, 50), dtype=bool)
    mask[5:12, 20:31] = True
    assert xyxy_from_mask(mask) == (20, 5, 31, 12)
    with pytest.raises(ValueError):
        xyxy_from_mask(np.zeros((4, 4), dtype=bool))
