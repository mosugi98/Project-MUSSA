import json

import numpy as np
import pytest

from cagsyntax.ai.segmenter import ModelUnavailable
from cagsyntax.ai.stenosis import Candidate, StenosisFinder, find_candidates
from tests.ai.toy_models import make_toy_model, write_card


def frame(h=80, w=60):
    return np.random.default_rng(0).integers(0, 255, size=(h, w)).astype(np.uint8)


def toy(tmp_path, logit=5.0, size=32, **card):
    model = make_toy_model(tmp_path / "stenosis.onnx", size=size, channels=1, positive=(0,), logit=logit)
    write_card(model, size=size, classes=["stenosis"], **card)
    return model


# ---- finding blobs ----
def blobs():
    p = np.full((50, 50), 0.05, dtype=np.float32)
    p[5:10, 5:12] = 0.9                       # 35 px
    p[30:40, 20:25] = 0.6                     # 50 px
    p[45, 45] = 0.99                          # 1 px: noise
    return p


def test_each_separate_blob_becomes_a_candidate_with_its_box_and_score():
    found = find_candidates(blobs(), threshold=0.5, min_pixels=10)
    assert len(found) == 2 and all(isinstance(c, Candidate) for c in found)
    first, second = found                                      # best score first
    assert first.box == (5, 5, 12, 10) and first.pixels == 35 and first.score == pytest.approx(0.9)
    assert second.box == (20, 30, 25, 40) and second.pixels == 50 and second.score == pytest.approx(0.6)
    assert first.mask.shape == (50, 50) and first.mask.dtype == bool and first.mask.sum() == 35


def test_tiny_blobs_are_dropped():
    assert len(find_candidates(blobs(), threshold=0.5, min_pixels=10)) == 2
    assert len(find_candidates(blobs(), threshold=0.5, min_pixels=1)) == 3
    assert len(find_candidates(blobs(), threshold=0.5, min_pixels=60)) == 0


def test_touching_pixels_join_diagonally():
    p = np.zeros((6, 6), dtype=np.float32)
    p[1, 1] = p[2, 2] = p[3, 3] = 0.9                          # a diagonal line is one object (8-connected)
    found = find_candidates(p, threshold=0.5, min_pixels=1)
    assert len(found) == 1 and found[0].pixels == 3


def test_nothing_above_the_threshold_gives_no_candidates():
    assert find_candidates(np.zeros((10, 10), np.float32), threshold=0.5, min_pixels=1) == []


def test_the_threshold_decides_what_counts():
    assert len(find_candidates(blobs(), threshold=0.7, min_pixels=10)) == 1


# ---- the model ----
def test_a_good_model_loads_and_finds_the_whole_frame_when_it_is_sure(tmp_path):
    finder = StenosisFinder.load(toy(tmp_path))
    found = finder.candidates(frame(80, 60))
    assert len(found) == 1 and found[0].mask.shape == (80, 60) and found[0].mask.all()
    assert found[0].box == (0, 0, 60, 80) and found[0].score > 0.99


def test_an_unsure_model_finds_nothing_until_the_threshold_is_lowered(tmp_path):
    finder = StenosisFinder.load(toy(tmp_path, logit=-0.5))     # sigmoid ~ 0.38
    assert finder.candidates(frame()) == []
    assert len(finder.candidates(frame(), threshold=0.3)) == 1


def test_the_card_threshold_is_used_by_default(tmp_path):
    finder = StenosisFinder.load(toy(tmp_path, logit=-0.5, thresholds={"stenosis": 0.3}))
    assert finder.threshold == 0.3 and len(finder.candidates(frame())) == 1


def test_the_input_is_not_modified(tmp_path):
    finder = StenosisFinder.load(toy(tmp_path))
    f = frame()
    before = f.copy()
    finder.candidates(f)
    assert (f == before).all()


@pytest.mark.parametrize("bad", [{"stenosis": 0.0}, {"stenosis": 1.5}, {"stenosis": "x"}, {"other": 0.3}, [0.3]])
def test_invalid_thresholds_are_refused(tmp_path, bad):
    with pytest.raises(ModelUnavailable):
        StenosisFinder.load(toy(tmp_path, thresholds=bad))


# ---- refusing a model that cannot be used ----
def test_a_missing_model_is_refused(tmp_path):
    with pytest.raises(ModelUnavailable):
        StenosisFinder.load(tmp_path / "stenosis.onnx")


def test_a_missing_or_broken_card_is_refused(tmp_path):
    model = make_toy_model(tmp_path / "stenosis.onnx", size=32, channels=1, positive=(0,))
    with pytest.raises(ModelUnavailable) as exc:
        StenosisFinder.load(model)
    assert "card" in str(exc.value).lower()
    (tmp_path / "stenosis.card.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(ModelUnavailable):
        StenosisFinder.load(model)


def test_the_segment_model_is_not_accepted_as_a_stenosis_model(tmp_path):
    model = make_toy_model(tmp_path / "stenosis.onnx", size=32, positive=(3,))             # 25 channels
    write_card(model, size=32)                                                              # the 25 segment names
    with pytest.raises(ModelUnavailable) as exc:
        StenosisFinder.load(model)
    assert "stenosis" in str(exc.value).lower()


def test_wrong_output_channels_are_refused(tmp_path):
    model = make_toy_model(tmp_path / "stenosis.onnx", size=32, channels=3, positive=(0,))
    write_card(model, size=32, classes=["stenosis"])
    with pytest.raises(ModelUnavailable):
        StenosisFinder.load(model)


def test_a_file_that_is_not_a_model_is_refused(tmp_path):
    (tmp_path / "stenosis.onnx").write_bytes(b"nope")
    write_card(tmp_path / "stenosis.onnx", size=32, classes=["stenosis"])
    with pytest.raises(ModelUnavailable):
        StenosisFinder.load(tmp_path / "stenosis.onnx")


def test_a_model_exported_with_symbolic_output_sizes_still_loads(tmp_path):
    model = make_toy_model(tmp_path / "stenosis.onnx", size=32, channels=1, positive=(0,), symbolic_output=True)
    write_card(model, size=32, classes=["stenosis"])
    assert StenosisFinder.load(model).candidates(frame())


def test_the_card_is_available_for_display(tmp_path):
    finder = StenosisFinder.load(toy(tmp_path))
    assert finder.card.trained_on == "toy test model" and json.loads(
        (tmp_path / "stenosis.card.json").read_text())["classes"] == ["stenosis"]
