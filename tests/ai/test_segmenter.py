import numpy as np
import pytest

from cagsyntax.ai.segmenter import ModelCard, ModelUnavailable, Segmenter
from tests.ai.toy_models import make_toy_model, write_card


def frame(h=100, w=80):
    return (np.random.default_rng(0).integers(0, 255, size=(h, w))).astype(np.uint8)


@pytest.fixture
def toy(tmp_path):
    model = make_toy_model(tmp_path / "segments.onnx", size=32, positive=(8, 9))
    write_card(model, size=32)
    return model


def test_a_good_model_loads_and_predicts_in_the_frames_own_size(toy):
    seg = Segmenter.load(toy)
    assert isinstance(seg.card, ModelCard) and seg.card.input_size == 32 and seg.card.trained_on == "toy test model"
    masks = seg.predict(frame(100, 80))
    assert masks.shape == (25, 100, 80) and masks.dtype == bool
    assert set(np.nonzero(masks.any(axis=(1, 2)))[0]) == {8, 9}
    assert masks[8].all() and masks[9].all()


def test_the_threshold_changes_the_result(tmp_path):
    model = make_toy_model(tmp_path / "segments.onnx", size=32, positive=(3,), logit=0.85)    # sigmoid ~ 0.70
    write_card(model, size=32)
    seg = Segmenter.load(model)
    assert seg.predict(frame(), threshold=0.5)[3].all()
    assert not seg.predict(frame(), threshold=0.8).any()


def test_predict_does_not_modify_its_input_and_is_deterministic(toy):
    seg = Segmenter.load(toy)
    f = frame()
    before = f.copy()
    a, b = seg.predict(f), seg.predict(f)
    assert np.array_equal(f, before) and np.array_equal(a, b)


def test_a_missing_model_file_is_reported(tmp_path):
    with pytest.raises(ModelUnavailable, match="No model file"):
        Segmenter.load(tmp_path / "segments.onnx")


def test_a_file_that_is_not_an_onnx_model_is_reported(tmp_path):
    bad = tmp_path / "segments.onnx"
    bad.write_bytes(b"random bytes" * 50)
    write_card(bad)
    with pytest.raises(ModelUnavailable, match="not a valid ONNX"):
        Segmenter.load(bad)


def test_a_model_without_its_card_is_reported(tmp_path):
    model = make_toy_model(tmp_path / "segments.onnx")
    with pytest.raises(ModelUnavailable, match="card"):
        Segmenter.load(model)


def test_an_unreadable_card_is_reported(toy):
    toy.with_name("segments.card.json").write_text("{not json")
    with pytest.raises(ModelUnavailable, match="card"):
        Segmenter.load(toy)


def test_a_card_with_the_wrong_class_list_is_rejected(tmp_path):
    model = make_toy_model(tmp_path / "segments.onnx")
    write_card(model, classes=["1", "2", "3"])
    with pytest.raises(ModelUnavailable, match="classes"):
        Segmenter.load(model)


def test_a_model_with_24_output_channels_is_rejected_not_drawn_wrong(tmp_path):  # Review Focus 2
    model = make_toy_model(tmp_path / "segments.onnx", channels=24, positive=(8,))
    write_card(model)
    with pytest.raises(ModelUnavailable, match="25"):
        Segmenter.load(model)


def test_a_model_with_the_wrong_input_shape_is_rejected(tmp_path):
    model = make_toy_model(tmp_path / "segments.onnx", in_channels=3)
    write_card(model)
    with pytest.raises(ModelUnavailable, match="input"):
        Segmenter.load(model)


def test_a_card_size_that_does_not_match_the_model_is_rejected(tmp_path):
    model = make_toy_model(tmp_path / "segments.onnx", size=32)
    write_card(model, size=64)
    with pytest.raises(ModelUnavailable, match="size"):
        Segmenter.load(model)
