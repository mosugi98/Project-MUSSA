import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from cagsyntax.ai.overlay import SEGMENT_COLORS, render_overlay, segment_labels
from cagsyntax.ai.segment_names import SEGMENT_NAMES
from cagsyntax.dicom_import.reader import read_xa
from cagsyntax.viewer.widget import AI_CAPTION, CineWidget
from tests.dicom_factory import make_xa


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def masks_with(**boxes):
    m = np.zeros((25, 40, 50), dtype=bool)
    for name, (r0, r1, c0, c1) in boxes.items():
        m[SEGMENT_NAMES.index(name), r0:r1, c0:c1] = True
    return m


def test_colors_cover_all_25_segments_and_are_distinct():
    assert list(SEGMENT_COLORS) == list(SEGMENT_NAMES) and len(set(SEGMENT_COLORS.values())) == 25
    assert all(len(c) == 3 and all(0 <= v <= 255 for v in c) for c in SEGMENT_COLORS.values())


def test_render_overlay_shape_dtype_and_transparency():
    out = render_overlay(masks_with(**{"5": (5, 15, 5, 15)}), alpha=100)
    assert out.shape == (40, 50, 4) and out.dtype == np.uint8
    assert tuple(out[10, 10, :3]) == SEGMENT_COLORS["5"] and out[10, 10, 3] == 100
    assert out[30, 30, 3] == 0 and out[0, 0, 3] == 0


def test_where_masks_overlap_the_later_segment_in_table_order_wins():
    out = render_overlay(masks_with(**{"5": (0, 20, 0, 20), "6": (10, 30, 10, 30)}))      # "6" comes after "5"
    assert tuple(out[15, 15, :3]) == SEGMENT_COLORS["6"]
    assert tuple(out[5, 5, :3]) == SEGMENT_COLORS["5"]


def test_wrong_mask_shape_is_rejected():
    with pytest.raises(ValueError):
        render_overlay(np.zeros((24, 10, 10), dtype=bool))


def test_segment_labels_give_names_and_centroids_of_non_empty_masks_only():
    labels = segment_labels(masks_with(**{"5": (0, 10, 0, 10), "9a": (20, 30, 30, 40)}))
    by_name = {name: (x, y) for name, x, y in labels}
    assert list(by_name) == ["5", "9a"] or set(by_name) == {"5", "9a"}
    assert by_name["5"] == pytest.approx((4.5, 4.5)) and by_name["9a"] == pytest.approx((34.5, 24.5))


# ---- viewer widget ----
def loaded_widget(tmp_path, frames=5):
    w = CineWidget()
    w.set_series(read_xa(make_xa(tmp_path / "a.dcm", frames=frames)), "view")
    return w


def test_the_widget_always_shows_the_ai_caption_with_an_overlay(qapp, tmp_path):  # Review Focus 3
    w = loaded_widget(tmp_path)
    assert not w.overlay_visible() and w.overlay_caption() == ""
    w.set_overlay(render_overlay(np.zeros((25, 64, 64), dtype=bool)), [])
    assert w.overlay_visible() and w.overlay_caption() == AI_CAPTION == "AI suggestion - not a diagnosis"
    w.set_overlay(render_overlay(np.zeros((25, 64, 64), dtype=bool)), [], caption="my caption")
    assert w.overlay_caption() == AI_CAPTION                    # a caller cannot remove the AI label
    w.clear_overlay()
    assert not w.overlay_visible() and w.overlay_caption() == ""


def test_set_overlay_none_clears_it(qapp, tmp_path):
    w = loaded_widget(tmp_path)
    w.set_overlay(render_overlay(np.zeros((25, 64, 64), dtype=bool)), [])
    w.set_overlay(None)
    assert not w.overlay_visible()


def test_changing_frame_clears_the_overlay_and_announces_the_new_frame(qapp, tmp_path):
    w = loaded_widget(tmp_path)
    w.set_overlay(render_overlay(np.zeros((25, 64, 64), dtype=bool)), [])
    spy = QSignalSpy(w.frame_changed)
    w.step_fwd_btn.click()
    assert not w.overlay_visible() and spy.count() == 1 and spy.at(0)[0] == 1


def test_current_frame_is_the_original_pixel_data_and_pausing_announces_the_frame(qapp, tmp_path):
    w = loaded_widget(tmp_path)
    series = read_xa(tmp_path / "a.dcm")
    assert w.frame_index() == 0 and np.array_equal(w.current_frame(), series.frames[0])
    w.play_btn.click()                                          # start: overlay is cleared while playing
    w.set_overlay(render_overlay(np.zeros((25, 64, 64), dtype=bool)), [])
    spy = QSignalSpy(w.frame_changed)
    w.play_btn.click()                                          # pause: the window may now refresh the overlay
    assert spy.count() == 1
    assert CineWidget().current_frame() is None
