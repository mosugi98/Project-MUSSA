import math

from cagsyntax.scoring.tables import SEGMENT_IDS
from cagsyntax.ui.artery_geo import ARTERY_GEO, bezier, midpoint, outline, sample


def test_table_covers_exactly_the_25_segments():
    assert set(ARTERY_GEO) == set(SEGMENT_IDS)
    assert len(ARTERY_GEO) == 25


def test_every_control_point_is_inside_the_picture_and_widths_are_positive():
    for seg, g in ARTERY_GEO.items():
        assert len(g.points) == 4, seg
        for x, y in g.points:
            assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0, (seg, x, y)
        assert g.width_start > 0 and g.width_end > 0, seg


def test_arteries_drawn_in_the_picture_are_marked_visible_and_hidden_ones_are_not():
    for seg in ("1", "2", "3", "6", "7", "8"):
        assert ARTERY_GEO[seg].visible, seg
    for seg in ("5", "11", "13", "14", "15", "16"):
        assert not ARTERY_GEO[seg].visible, seg


def test_bezier_endpoints_and_midpoint_of_a_straight_line():
    pts = ((0.0, 0.5), (1 / 3, 0.5), (2 / 3, 0.5), (1.0, 0.5))
    assert bezier(pts, 0.0) == (0.0, 0.5)
    assert bezier(pts, 1.0) == (1.0, 0.5)
    x, y = bezier(pts, 0.5)
    assert math.isclose(x, 0.5) and math.isclose(y, 0.5)


def test_sample_returns_n_plus_one_points_ending_on_the_curve_ends():
    pts = ARTERY_GEO["6"].points
    s = sample(pts, 24)
    assert len(s) == 25
    assert s[0] == bezier(pts, 0.0) and s[-1] == bezier(pts, 1.0)


def test_midpoint_matches_the_bezier_at_one_half():
    assert midpoint("8") == bezier(ARTERY_GEO["8"].points, 0.5)


def test_outline_is_a_ribbon_that_tapers():
    line = ((0.0, 0.5), (1 / 3, 0.5), (2 / 3, 0.5), (1.0, 0.5))
    poly = outline(sample(line, 10), 0.10, 0.02)
    assert len(poly) == 22                                    # 11 points down one side, 11 back up the other
    ys_start = [y for x, y in poly if x < 0.01]
    ys_end = [y for x, y in poly if x > 0.99]
    assert math.isclose(max(ys_start) - min(ys_start), 0.10, abs_tol=1e-9)
    assert math.isclose(max(ys_end) - min(ys_end), 0.02, abs_tol=1e-9)
