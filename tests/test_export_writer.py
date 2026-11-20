import csv
import hashlib
import json
from pathlib import Path

import pytest

from cagsyntax.cases import study_of
from cagsyntax.export import writer as writer_module
from cagsyntax.export.dataset import build_dataset
from cagsyntax.export.writer import ExportResult, write_export
from tests.test_export_build import confirm, world  # noqa: F401  (world is a fixture)
from tests.test_export_dataset import STUDY_A, STUDY_B

CASE_COLUMNS = ["case_id", "patient_key", "suggested_split", "reference_total", "reference_group",
                "dominance", "scoring_dominance", "n_lesions", "n_series", "n_cines",
                "consistent_with_engine"]
SERIES_COLUMNS = ["case_id", "series_id", "kind", "view", "frames", "burned_in_unclear", "path"]


def export(world, out_name="out", copy_images=False, include_stills=False, confirm_b=False):
    lib, store, uid_a, uid_b, tmp = world
    confirm(store, uid_a)
    if confirm_b:
        confirm(store, uid_b, mrn_hash="hash-B")
    ds = build_dataset(store, lib, include_stills=include_stills)
    return write_export(ds, lib, tmp / out_name, copy_images=copy_images), tmp / out_name, ds


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def test_files_columns_and_counts(world):
    result, out, ds = export(world, confirm_b=True)
    assert isinstance(result, ExportResult) and result.folder == out
    assert (result.cases, result.series, result.excluded, result.inconsistent, result.images_copied) == (2, 3, 0, 0, 0)
    assert sorted(p.name for p in out.iterdir()) == ["README.txt", "cases.csv", "dataset.json", "series.csv"]
    cases = read_csv(out / "cases.csv")
    series = read_csv(out / "series.csv")
    assert cases[0] == CASE_COLUMNS and len(cases) == 3
    assert series[0] == SERIES_COLUMNS and len(series) == 4
    row = dict(zip(CASE_COLUMNS, cases[1]))
    assert row["reference_total"] == "5.0" and row["dominance"] == "right" and row["scoring_dominance"] == "right"
    assert row["consistent_with_engine"] == "True" and row["suggested_split"] in ("train", "val", "test")
    data = json.loads((out / "dataset.json").read_text(encoding="utf-8"))
    assert data["format_version"] == 1 and data["engine"]["version"] and data["engine"]["source"].startswith("https://")
    assert data["options"] == {"include_stills": False, "images_copied": False}
    assert "not a certified medical device" in data["notice"].lower()
    assert data["counts"] == {"cases": 2, "series": 3, "excluded": 0, "inconsistent": 0,
                              "burned_in_unclear": 0, "without_patient_key": 0}
    assert len(data["cases"]) == 2 and data["excluded"] == []
    first = data["cases"][0]
    assert {"case_id", "patient_key", "suggested_split", "confirmed_at", "confirmed_by_level", "reference",
            "rescored", "series"} <= set(first)
    assert all(s["path"].startswith("store/") and "sha256" not in s for s in first["series"])


def test_no_identifiers_anywhere_in_the_export(world):  # Review Focus 1
    lib, store, uid_a, uid_b, tmp = world
    lib.assign([e.uid for e in lib.entries()], "Patient John Doe case")
    result, out, _ = export(world, copy_images=True, include_stills=True, confirm_b=True)
    needles = ["Dr Secret Name", "Secret", "Patient John Doe", "secret_name", "DOE", "JOHN", "MRN12345",
               "MRN99999", STUDY_A, STUDY_B, "Data CAG", str(tmp), "D:\\", "C:\\"]
    for f in out.rglob("*"):
        if f.is_file() and f.suffix != ".dcm":
            text = f.read_text(encoding="utf-8")
            for needle in needles:
                assert needle not in text, (f.name, needle)
        assert not any(n in f.name for n in ("secret", "Secret", "DOE"))
    for f in (out / "images").glob("*.dcm"):                              # copied images are the de-identified ones
        raw = f.read_bytes()
        assert b"DOE" not in raw and b"MRN12345" not in raw


def test_a_failed_write_leaves_nothing_behind(world, monkeypatch):  # Review Focus 2
    lib, store, uid_a, _, tmp = world
    confirm(store, uid_a)
    ds = build_dataset(store, lib)

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(writer_module.json, "dumps", boom)
    with pytest.raises(RuntimeError):
        write_export(ds, lib, tmp / "out")
    assert list(tmp.glob("out*")) == []


def test_a_non_empty_target_is_refused_and_untouched(world):  # Review Focus 2
    lib, store, uid_a, _, tmp = world
    confirm(store, uid_a)
    ds = build_dataset(store, lib)
    (tmp / "out").mkdir()
    (tmp / "out" / "mine.txt").write_text("keep me")
    with pytest.raises(FileExistsError):
        write_export(ds, lib, tmp / "out")
    assert sorted(p.name for p in (tmp / "out").iterdir()) == ["mine.txt"]
    assert (tmp / "out" / "mine.txt").read_text() == "keep me"
    assert list(tmp.glob("out.tmp*")) == []


def test_an_existing_empty_folder_is_accepted(world):
    lib, store, uid_a, _, tmp = world
    confirm(store, uid_a)
    (tmp / "out").mkdir()
    write_export(build_dataset(store, lib), lib, tmp / "out")
    assert (tmp / "out" / "dataset.json").exists()


def test_copied_images_keep_their_pixels_and_have_matching_checksums(world):
    import numpy as np
    import pydicom
    result, out, ds = export(world, copy_images=True)
    lib = world[0]
    data = json.loads((out / "dataset.json").read_text(encoding="utf-8"))
    assert result.images_copied == 2 and data["options"]["images_copied"] is True
    for s in data["cases"][0]["series"]:
        copied = out / s["path"]
        assert s["path"] == f"images/{s['series_id']}.dcm" and copied.exists()
        original = pydicom.dcmread(lib.store_dir / f"{s['series_id']}.dcm")
        again = pydicom.dcmread(copied)
        assert np.array_equal(again.pixel_array, original.pixel_array)
        assert s["sha256"] == hashlib.sha256(copied.read_bytes()).hexdigest()
    assert {r[6] for r in read_csv(out / "series.csv")[1:]} == {f"images/{s['series_id']}.dcm" for s in data["cases"][0]["series"]}


def test_without_copying_no_images_folder_exists(world):
    _, out, _ = export(world)
    assert not (out / "images").exists()


def test_repeat_exports_are_identical_apart_from_the_created_time(world):
    lib, store, uid_a, uid_b, tmp = world
    confirm(store, uid_a)
    confirm(store, uid_b, mrn_hash="hash-B")
    for name in ("one", "two"):
        write_export(build_dataset(store, lib), lib, tmp / name)
    a = json.loads((tmp / "one" / "dataset.json").read_text(encoding="utf-8"))
    b = json.loads((tmp / "two" / "dataset.json").read_text(encoding="utf-8"))
    a.pop("created"), b.pop("created")
    assert a == b
    for name in ("cases.csv", "series.csv"):
        assert (tmp / "one" / name).read_text(encoding="utf-8") == (tmp / "two" / name).read_text(encoding="utf-8")


def test_readme_warns_about_inconsistent_and_excluded_cases(world):
    lib, store, uid_a, uid_b, tmp = world
    confirm(store, uid_a)
    confirm(store, uid_b, mrn_hash="hash-B")
    store._con.execute("UPDATE confirmations SET total = 99.0, grp = 'high' WHERE study_uid = ?", (uid_a,))
    store._con.commit()
    for e in lib.entries():
        if study_of(e.path)[0] == uid_b:
            lib.delete_series(e.uid)
    result = write_export(build_dataset(store, lib), lib, tmp / "out")
    readme = (tmp / "out" / "README.txt").read_text(encoding="utf-8")
    assert (result.inconsistent, result.excluded) == (1, 1)
    assert "WARNING" in readme and "99" in readme and "NOT EXPORTED" in readme and "no series" in readme
    assert "not a certified medical device" in readme.lower() and "70" in readme and "small" in readme.lower()


def test_nothing_to_export_raises_and_creates_nothing(world):
    lib, store, _, _, tmp = world
    with pytest.raises(ValueError, match="no confirmed"):
        write_export(build_dataset(store, lib), lib, tmp / "out")
    assert list(tmp.glob("out*")) == []
