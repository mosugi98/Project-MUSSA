import pytest

from cagsyntax.dicom_import.views import label_view


@pytest.mark.parametrize("primary,secondary,expected", [
    (30, 20, "LAO 30 CRAN 20"),
    (-45, -25, "RAO 45 CAUD 25"),
    (0, 0, "AP"),
    (0.4, 30, "CRAN 30"),
    (None, 20, "Unknown view"),
    (30, None, "Unknown view"),
])
def test_label_view(primary, secondary, expected):
    assert label_view(primary, secondary) == expected
