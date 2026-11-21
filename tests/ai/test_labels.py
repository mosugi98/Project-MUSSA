import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from cagsyntax.ai.arcade import ArcadeSplit
from cagsyntax.ai.segment_names import SEGMENT_NAMES
from cagsyntax.ai.labels import check_coco, export_frames, format_check, split_coco
from cagsyntax.dicom_import.importer import import_path
from tests.ai.test_arcade import make_split
from tests.dicom_factory import make_xa

ROOT = Path(__file__).resolve().parents[2]
SALT = b"s" * 32


def make_store(tmp_path, n=2, frames=5):
    src = tmp_path / "in"
    src.mkdir()
    for i in range(n):
        make_xa(src / f"a{i}.dcm", frames=frames, primary=30.0 + i, mrn="MRN12345", name="DOE^JOHN")
    store = tmp_path / "store"
    result = import_path(src, store, SALT)
    assert len(result.imported) == n
    return store


# ---------------------------------------------------------------- frames for labelling
def test_the_middle_frame_of_each_series_becomes_an_8_bit_png_with_a_traceable_name(tmp_path):
    store = make_store(tmp_path)
    result = export_frames(store, tmp_path / "png")
    pngs = sorted((tmp_path / "png").glob("*.png"))
    assert len(pngs) == 2 and len(result.written) == 2 and result.skipped == []
    im = Image.open(pngs[0])
    assert im.mode == "L" and im.size == (64, 64)
    assert all(p.stem.endswith("_f2") for p in pngs)                         # frame 2 of 0..4 = the middle


def test_frames_csv_links_each_png_to_its_series_study_and_frame(tmp_path):
    store = make_store(tmp_path)
    export_frames(store, tmp_path / "png")
    rows = list(csv.DictReader((tmp_path / "png" / "frames.csv").open(encoding="utf-8")))
    assert len(rows) == 2 and set(rows[0]) == {"file", "series_uid", "study_uid", "frame"}
    assert all((tmp_path / "png" / r["file"]).exists() and r["frame"] == "2" for r in rows)
    assert all(r["series_uid"].startswith("2.25.") and r["study_uid"].startswith("2.25.") for r in rows)


def test_nothing_that_identifies_the_patient_reaches_the_output(tmp_path):
    store = make_store(tmp_path)
    export_frames(store, tmp_path / "png")
    text = " ".join(p.name for p in (tmp_path / "png").iterdir()) + (tmp_path / "png" / "frames.csv").read_text()
    assert "MRN12345" not in text and "DOE" not in text and "JOHN" not in text


def test_a_chosen_frame_all_frames_and_out_of_range_frames(tmp_path):
    store = make_store(tmp_path, n=1)
    export_frames(store, tmp_path / "one", frame=1)
    assert [p.stem[-2:] for p in (tmp_path / "one").glob("*.png")] == ["f1"]
    export_frames(store, tmp_path / "all", frame="all")
    assert len(list((tmp_path / "all").glob("*.png"))) == 5
    result = export_frames(store, tmp_path / "far", frame=99)
    assert result.written == [] and "frame 99" in result.skipped[0][1]


def test_a_file_that_cannot_be_read_is_skipped_and_the_rest_are_exported(tmp_path):
    store = make_store(tmp_path)
    (store / "broken.dcm").write_bytes(b"not dicom")
    result = export_frames(store, tmp_path / "png")
    assert len(result.written) == 2 and [name for name, _ in result.skipped] == ["broken.dcm"]


def test_a_folder_that_already_has_files_is_refused(tmp_path):
    store = make_store(tmp_path)
    out = tmp_path / "png"
    out.mkdir()
    (out / "mine.txt").write_text("keep")
    with pytest.raises(ValueError):
        export_frames(store, out)
    assert (out / "mine.txt").read_text() == "keep"


def test_a_series_with_one_frame_exports_that_frame(tmp_path):
    store = make_store(tmp_path, n=1, frames=1)
    assert len(export_frames(store, tmp_path / "png").written) == 1


# ---------------------------------------------------------------- checking a labelled folder
def test_a_good_labelled_folder_passes_and_is_counted(tmp_path):
    report = check_coco(make_split(tmp_path))
    assert report.ok and report.images == 2 and report.annotations == 5
    assert report.per_category == {"5": 1, "6": 2, "9a": 1, "stenosis": 1}
    assert "1" in report.never_labelled and "5" not in report.never_labelled


def test_the_report_is_in_plain_words(tmp_path):
    text = format_check(check_coco(make_split(tmp_path)))
    assert "2 images" in text and "OK" in text and "never labelled" in text.lower()


def test_a_cvat_style_export_is_found_too(tmp_path):
    root = make_split(tmp_path)
    (root / "annotations" / "train.json").rename(root / "annotations" / "instances_default.json")
    assert check_coco(root).ok


def test_no_annotation_file_is_a_problem(tmp_path):
    (tmp_path / "x" / "images").mkdir(parents=True)
    report = check_coco(tmp_path / "x")
    assert not report.ok and "annotation file" in report.problems[0].lower()


def test_unreadable_json_is_a_problem(tmp_path):
    root = make_split(tmp_path)
    (root / "annotations" / "train.json").write_text("{broken", encoding="utf-8")
    assert not check_coco(root).ok


def test_a_missing_image_file_is_named(tmp_path):
    root = make_split(tmp_path)
    (root / "images" / "2.png").unlink()
    report = check_coco(root)
    assert not report.ok and any("2.png" in p for p in report.problems)


def edit_json(root, change):
    path = root / "annotations" / "train.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_a_label_that_is_not_a_syntax_segment_is_a_problem_and_a_typo_is_suggested(tmp_path):
    root = make_split(tmp_path)
    edit_json(root, lambda d: d["categories"].append({"id": 7, "name": "LAD"}))
    edit_json(root, lambda d: d["annotations"].append(
        {"id": 9, "image_id": 1, "category_id": 7, "segmentation": [[1, 1, 9, 1, 9, 9]]}))
    report = check_coco(root)
    assert not report.ok and any("'LAD'" in p for p in report.problems)


def test_a_label_with_odd_spacing_or_case_is_explained(tmp_path):
    root = make_split(tmp_path)
    edit_json(root, lambda d: d["categories"].append({"id": 7, "name": " 9A "}))
    edit_json(root, lambda d: d["annotations"].append(
        {"id": 9, "image_id": 1, "category_id": 7, "segmentation": [[1, 1, 9, 1, 9, 9]]}))
    assert any("9a" in p for p in check_coco(root).problems)


def test_a_polygon_with_fewer_than_three_points_is_a_problem(tmp_path):
    root = make_split(tmp_path)
    edit_json(root, lambda d: d["annotations"][0].update(segmentation=[[1, 1, 5, 5]]))
    assert any("3 points" in p for p in check_coco(root).problems)


def test_a_brush_mask_instead_of_a_polygon_is_a_problem(tmp_path):
    root = make_split(tmp_path)
    edit_json(root, lambda d: d["annotations"][0].update(segmentation={"counts": [1, 2], "size": [64, 64]}))
    assert any("polygon" in p.lower() for p in check_coco(root).problems)


def test_an_annotation_pointing_at_a_missing_image_is_a_problem(tmp_path):
    root = make_split(tmp_path)
    edit_json(root, lambda d: d["annotations"][0].update(image_id=999))
    assert not check_coco(root).ok


def test_images_without_labels_are_counted_as_a_warning_not_a_problem(tmp_path):
    root = make_split(tmp_path)
    edit_json(root, lambda d: d.update(annotations=[a for a in d["annotations"] if a["image_id"] == 1]))
    report = check_coco(root)
    assert report.ok and report.unlabelled_images == 1 and any("no labels" in w for w in report.warnings)


def test_few_images_are_a_warning(tmp_path):
    report = check_coco(make_split(tmp_path))
    assert any("only 2 images" in w.lower() for w in report.warnings)


# ---------------------------------------------------------------- splitting
def big_source(tmp_path, groups=10, per_group=2):
    """A CVAT-style export with `groups` studies of `per_group` images, plus a frames.csv."""
    root = tmp_path / "cvat"
    (root / "images").mkdir(parents=True)
    (root / "annotations").mkdir()
    images, anns, rows = [], [], []
    n = 0
    for g in range(groups):
        for k in range(per_group):
            n += 1
            name = f"s{g}_{k}.png"
            Image.fromarray(np.full((32, 32), 100, dtype=np.uint8)).save(root / "images" / name)
            images.append({"id": n, "width": 32, "height": 32, "file_name": name})
            anns.append({"id": n, "image_id": n, "category_id": 1, "segmentation": [[2, 2, 20, 2, 20, 20, 2, 20]]})
            rows.append({"file": name, "series_uid": f"2.25.{n}", "study_uid": f"2.25.9{g}", "frame": "2"})
    (root / "annotations" / "instances_default.json").write_text(
        json.dumps({"images": images, "annotations": anns, "categories": [{"id": 1, "name": "5"}, {"id": 2, "name": "stenosis"}]}),
        encoding="utf-8")
    with (root / "frames.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "series_uid", "study_uid", "frame"])
        w.writeheader()
        w.writerows(rows)
    return root


def test_the_split_makes_arcade_style_train_and_val_folders_the_loader_can_read(tmp_path):
    out = tmp_path / "labelled"
    result = split_coco(big_source(tmp_path), out, val_fraction=0.2)
    assert result.train_images + result.val_images == 20 and result.val_images >= 2
    for name in ("train", "val"):
        split = ArcadeSplit(out / name)
        assert len(split) == (result.train_images if name == "train" else result.val_images)
        assert split.load_masks(0)[SEGMENT_NAMES.index("5")].any()             # category "5" loads as segment "5"


def test_images_of_one_study_never_land_in_both_splits(tmp_path):
    out = tmp_path / "labelled"
    split_coco(big_source(tmp_path), out, val_fraction=0.3)
    studies = {}
    for name in ("train", "val"):
        for row in json.loads((out / name / "annotations" / f"{name}.json").read_text())["images"]:
            studies.setdefault(row["file_name"].split("_")[0], set()).add(name)
    assert all(len(v) == 1 for v in studies.values())


def test_the_split_is_repeatable(tmp_path):
    src = big_source(tmp_path)
    a, b = split_coco(src, tmp_path / "a"), split_coco(src, tmp_path / "b")
    assert (a.train_images, a.val_images) == (b.train_images, b.val_images)
    assert (tmp_path / "a" / "val" / "annotations" / "val.json").read_text() == (tmp_path / "b" / "val" / "annotations" / "val.json").read_text()


def test_without_frames_csv_each_image_is_its_own_group(tmp_path):
    src = big_source(tmp_path)
    (src / "frames.csv").unlink()
    result = split_coco(src, tmp_path / "labelled")
    assert result.train_images + result.val_images == 20


def test_too_few_images_to_split_is_refused_with_a_reason(tmp_path):
    src = big_source(tmp_path, groups=1, per_group=1)
    with pytest.raises(ValueError) as exc:
        split_coco(src, tmp_path / "labelled")
    assert "at least 2" in str(exc.value)


def test_a_non_empty_target_is_refused(tmp_path):
    out = tmp_path / "labelled"
    out.mkdir()
    (out / "x.txt").write_text("keep")
    with pytest.raises(ValueError):
        split_coco(big_source(tmp_path), out)


def test_a_bad_val_fraction_is_refused(tmp_path):
    src = big_source(tmp_path)
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            split_coco(src, tmp_path / f"o{bad}", val_fraction=bad)


# ---------------------------------------------------------------- command line
def run(*args):
    return subprocess.run([sys.executable, str(ROOT / "tools" / "labelling" / "mussa_labels.py"), *map(str, args)],
                          capture_output=True, text=True, timeout=120)


def test_the_command_line_frames_check_and_split_work_end_to_end(tmp_path):
    store = make_store(tmp_path)
    done = run("frames", "--store", store, "--out", tmp_path / "png")
    assert done.returncode == 0 and "2 image" in done.stdout
    done = run("check", "--folder", make_split(tmp_path / "c"))
    assert done.returncode == 0 and "OK" in done.stdout
    done = run("split", "--source", big_source(tmp_path), "--out", tmp_path / "labelled")
    assert done.returncode == 0 and "train" in done.stdout


def test_the_command_line_check_exits_nonzero_when_there_are_problems(tmp_path):
    root = make_split(tmp_path)
    (root / "images" / "2.png").unlink()
    done = run("check", "--folder", root)
    assert done.returncode == 1 and "2.png" in done.stdout
