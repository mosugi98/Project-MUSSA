import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from cagsyntax.ai.arcade import SEGMENT_NAMES, ArcadeSplit, polygon_to_mask
from cagsyntax.scoring.tables import SEGMENT_IDS

REAL = Path(__file__).resolve().parents[2] / "arcade" / "arcade" / "syntax" / "train"


def make_split(tmp_path, extra_category=False):
    root = tmp_path / "syntax" / "train"
    (root / "images").mkdir(parents=True)
    (root / "annotations").mkdir()
    for name in ("1.png", "2.png"):
        Image.fromarray(np.full((64, 64), 128, dtype=np.uint8)).save(root / "images" / name)
    cats = [{"id": 1, "name": "5"}, {"id": 2, "name": "6"}, {"id": 3, "name": "9a"}, {"id": 4, "name": "stenosis"}]
    if extra_category:
        cats.append({"id": 5, "name": "99"})
    square = [10, 10, 30, 10, 30, 30, 10, 30]
    anns = [
        {"id": 1, "image_id": 1, "category_id": 1, "segmentation": [square]},
        {"id": 2, "image_id": 1, "category_id": 2, "segmentation": [[40, 5, 50, 5, 50, 15, 40, 15]]},
        {"id": 3, "image_id": 1, "category_id": 2, "segmentation": [[40, 40, 50, 40, 50, 50, 40, 50]]},
        {"id": 4, "image_id": 1, "category_id": 4, "segmentation": [[1, 1, 5, 1, 5, 5, 1, 5]]},
        {"id": 5, "image_id": 2, "category_id": 3, "segmentation": [[50, 50, 70, 50, 70, 70, 50, 70]]},   # runs off the image
    ]
    images = [{"id": 1, "width": 64, "height": 64, "file_name": "1.png"},
              {"id": 2, "width": 64, "height": 64, "file_name": "2.png"}]
    (root / "annotations" / "train.json").write_text(
        json.dumps({"images": images, "annotations": anns, "categories": cats}), encoding="utf-8")
    return root


def test_segment_names_are_our_25_segments_in_table_order():
    assert SEGMENT_NAMES == tuple(SEGMENT_IDS) and len(SEGMENT_NAMES) == 25


def test_polygon_square_area_and_position():
    m = polygon_to_mask([10, 10, 30, 10, 30, 30, 10, 30], 64, 64)
    assert m.dtype == bool and m.shape == (64, 64)
    assert abs(int(m.sum()) - 400) < 60
    assert m[20, 20] and not m[20, 40]


def test_polygon_uses_x_then_y_order():
    m = polygon_to_mask([5, 10, 45, 10, 45, 20, 5, 20], 64, 64)       # wide rectangle: columns 5-45, rows 10-20
    assert m[15, 40] and not m[40, 15]


def test_degenerate_polygons_give_empty_masks():
    assert not polygon_to_mask([1, 1, 5, 5], 64, 64).any()
    assert not polygon_to_mask([], 64, 64).any()


def test_points_beyond_the_image_are_clipped_without_error():
    m = polygon_to_mask([50, 50, 90, 50, 90, 90, 50, 90], 64, 64)
    assert m[60, 60] and m.shape == (64, 64)


def test_split_loads_images_ids_and_counts(tmp_path):
    split = ArcadeSplit(make_split(tmp_path))
    assert len(split) == 2 and split.image_ids == [1, 2]
    img = split.load_image(0)
    assert img.dtype == np.uint8 and img.shape == (64, 64)
    assert split.class_counts() == {"5": 1, "6": 2, "9a": 1}


def test_masks_follow_segment_order_or_polygons_and_ignore_stenosis(tmp_path):
    split = ArcadeSplit(make_split(tmp_path))
    masks = split.load_masks(0)
    assert masks.shape == (25, 64, 64) and masks.dtype == bool
    ch5, ch6, ch9a = (SEGMENT_NAMES.index(n) for n in ("5", "6", "9a"))
    assert masks[ch5, 20, 20] and not masks[ch5, 10, 45]
    assert masks[ch6, 10, 45] and masks[ch6, 45, 45]                   # two polygons of "6" are OR-ed
    assert not masks[ch9a].any()
    assert int(masks.any(axis=(1, 2)).sum()) == 2                      # the stenosis annotation set no channel
    assert not masks[:, 3, 3].any()
    assert split.load_masks(1)[ch9a, 60, 60]


def test_unknown_category_name_is_rejected(tmp_path):
    root = make_split(tmp_path, extra_category=True)
    ann = json.loads((root / "annotations" / "train.json").read_text())
    ann["annotations"].append({"id": 9, "image_id": 1, "category_id": 5, "segmentation": [[1, 1, 9, 1, 9, 9]]})
    (root / "annotations" / "train.json").write_text(json.dumps(ann))
    with pytest.raises(ValueError, match="99"):
        ArcadeSplit(root)


def test_a_non_polygon_segmentation_is_rejected(tmp_path):
    root = make_split(tmp_path)
    ann = json.loads((root / "annotations" / "train.json").read_text())
    ann["annotations"][0]["segmentation"] = {"counts": "abc", "size": [64, 64]}
    (root / "annotations" / "train.json").write_text(json.dumps(ann))
    with pytest.raises(ValueError, match="polygon"):
        ArcadeSplit(root)


@pytest.mark.skipif(not REAL.exists(), reason="real ARCADE data not present in arcade/arcade/syntax/train")
def test_real_arcade_categories_match_our_segments_and_images_load():
    split = ArcadeSplit(REAL)
    assert set(split.class_counts()) <= set(SEGMENT_NAMES)
    i = split.image_ids.index(922)
    img, masks = split.load_image(i), split.load_masks(i)
    assert img.shape == (512, 512) and img.dtype == np.uint8
    assert masks.shape == (25, 512, 512) and int(masks.any(axis=(1, 2)).sum()) >= 2


def test_segment_names_live_in_a_dependency_free_module_that_matches_the_engine():
    """The training kit gets copies of ai/*.py without the rest of the project, so these modules may
    import only numpy, Pillow, the standard library and each other."""
    from cagsyntax.ai import segment_names
    assert segment_names.SEGMENT_NAMES == tuple(SEGMENT_IDS)
    src = Path(segment_names.__file__).read_text(encoding="utf-8")
    arcade_src = (Path(segment_names.__file__).parent / "arcade.py").read_text(encoding="utf-8")
    for text in (src, arcade_src):
        assert "scoring" not in text and "cagsyntax" not in text
