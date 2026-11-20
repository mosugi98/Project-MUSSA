from pathlib import Path

import numpy as np
import pytest

from cagsyntax.ai import preprocess as pre
from cagsyntax.ai.preprocess import INPUT_SIZE, preprocess, resize_mask


def gradient(h=100, w=80, dtype=np.uint8):
    base = np.tile(np.linspace(0, 255, w), (h, 1))
    return base.astype(dtype)


def test_output_shape_dtype_for_different_inputs():
    for frame in (gradient(100, 80), gradient(512, 512), gradient(64, 200, np.uint16) * 200):
        out = preprocess(frame)
        assert out.shape == (1, INPUT_SIZE, INPUT_SIZE) and out.dtype == np.float32
    assert INPUT_SIZE == 512


def test_values_span_exactly_minus_one_to_one_for_a_full_range_frame():
    out = preprocess(gradient())
    assert out.min() == pytest.approx(-1.0, abs=1e-5) and out.max() == pytest.approx(1.0, abs=1e-5)


def test_a_constant_frame_gives_zeros_without_warnings(recwarn):
    out = preprocess(np.full((50, 50), 77, dtype=np.uint8))
    assert np.all(out == 0.0) and not recwarn.list


def test_result_does_not_depend_on_the_overall_brightness_scale():
    frame = (gradient(60, 60, np.uint16) * 100).astype(np.uint16)
    assert np.allclose(preprocess(frame), preprocess((frame * 2).astype(np.uint16)), atol=1e-4)


def test_input_is_not_modified():
    frame = gradient()
    before = frame.copy()
    preprocess(frame)
    assert np.array_equal(frame, before)


def test_non_2d_input_is_rejected():
    with pytest.raises(ValueError):
        preprocess(np.zeros((4, 4, 3), dtype=np.uint8))


def test_resize_mask_keeps_bool_and_geometry():
    mask = np.zeros((512, 512), dtype=bool)
    mask[:, :256] = True                                   # left half
    out = resize_mask(mask, 100, 80)
    assert out.dtype == bool and out.shape == (100, 80)
    assert out[:, :39].all() and not out[:, 41:].any()


def test_the_module_imports_only_numpy_and_pillow_so_the_kit_can_copy_it():
    src = Path(pre.__file__).read_text(encoding="utf-8")
    assert "cagsyntax" not in src and "scoring" not in src
    imports = [line.split()[1].split(".")[0] for line in src.splitlines() if line.startswith(("import ", "from "))]
    assert set(imports) <= {"__future__", "numpy", "PIL"}


def test_an_optional_size_gives_a_smaller_input_for_small_models():
    out = preprocess(gradient(100, 80), size=128)
    assert out.shape == (1, 128, 128) and out.dtype == np.float32
    assert out.min() == pytest.approx(-1.0, abs=1e-5) and out.max() == pytest.approx(1.0, abs=1e-5)
    assert preprocess(gradient()).shape == (1, 512, 512)                    # default unchanged
