import math

import pytest

from cagsyntax.ai.sampling import rare_segment_weights


def test_an_image_with_a_rare_segment_weighs_more_than_one_with_only_the_commonest():
    counts = [{"1": 1}] * 9 + [{"16a": 1}]                 # "1" is in 9 images, "16a" in 1
    w = rare_segment_weights(counts)
    assert w[9] > w[0] * 2


def test_an_image_without_any_segment_gets_the_base_weight():
    w = rare_segment_weights([{"1": 1}, {}, {"1": 1}])
    assert w[1] == pytest.approx(1.0) and all(x >= 1.0 for x in w)


def test_the_rarest_segment_in_an_image_decides_its_weight():
    counts = [{"1": 1}] * 9 + [{"1": 1, "16a": 1}]
    w = rare_segment_weights(counts)
    assert w[9] > w[0]


def test_power_zero_gives_equal_weights():
    assert set(rare_segment_weights([{"1": 1}] * 3 + [{"16a": 1}], power=0.0)) == {1.0}


def test_weights_are_positive_finite_and_cover_every_image():
    counts = [{"1": 2, "5": 1}, {}, {"9a": 1}, {"5": 3}]
    w = rare_segment_weights(counts)
    assert len(w) == 4 and all(x > 0 and math.isfinite(x) for x in w)


def test_a_larger_power_favours_rare_segments_more():
    counts = [{"1": 1}] * 9 + [{"16a": 1}]
    assert rare_segment_weights(counts, power=1.0)[9] > rare_segment_weights(counts, power=0.5)[9]


def test_negative_power_is_refused():
    with pytest.raises(ValueError):
        rare_segment_weights([{"1": 1}], power=-1.0)


def test_empty_input_gives_empty_output():
    assert rare_segment_weights([]) == []
