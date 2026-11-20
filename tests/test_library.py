import json

import pytest

from cagsyntax.library import DEFAULT_LABEL, Library


@pytest.fixture
def lib(tmp_path):
    store = tmp_path / "data" / "store"
    store.mkdir(parents=True)
    for uid in ("2.25.1", "2.25.2", "2.25.3"):
        (store / f"{uid}.dcm").write_bytes(b"x")
    return Library(tmp_path / "data")


def test_entries_default_to_unsorted(lib):
    assert [e.label for e in lib.entries()] == [DEFAULT_LABEL] * 3
    assert [e.uid for e in lib.entries()] == ["2.25.1", "2.25.2", "2.25.3"]


def test_assign_sets_labels_sorted_and_trimmed(lib):
    lib.assign(["2.25.1", "2.25.2"], "  Case 01 ")
    lib.assign(["2.25.3"], "Case 00")
    assert lib.labels() == ["Case 00", "Case 01"]
    assert [e.label for e in lib.entries()] == ["Case 00", "Case 01", "Case 01"]


def test_empty_label_becomes_unsorted(lib):
    lib.assign(["2.25.1"], "   ")
    assert lib.entries()[0].label == DEFAULT_LABEL


def test_labels_persist_across_instances(lib, tmp_path):
    lib.assign(["2.25.1"], "Case 01")
    assert Library(tmp_path / "data").labels() == ["Case 01", DEFAULT_LABEL]


def test_delete_series_removes_file_and_label(lib, tmp_path):
    lib.assign(["2.25.1"], "Case 01")
    assert lib.delete_series("2.25.1") is True
    assert not (tmp_path / "data" / "store" / "2.25.1.dcm").exists()
    assert "2.25.1" not in json.loads((tmp_path / "data" / "folders.json").read_text())
    assert lib.delete_series("2.25.1") is False


def test_delete_folder_removes_only_that_folder(lib, tmp_path):
    lib.assign(["2.25.1", "2.25.2"], "Case 01")
    assert lib.delete_folder("Case 01") == 2
    assert [e.uid for e in lib.entries()] == ["2.25.3"]


def test_delete_series_rejects_path_traversal(lib, tmp_path):
    outside = tmp_path / "data" / "keep.dcm"
    outside.write_bytes(b"x")
    with pytest.raises(ValueError):
        lib.delete_series("../keep")
    assert outside.exists()


def test_corrupt_index_does_not_crash(lib, tmp_path):
    (tmp_path / "data" / "folders.json").write_text("{not json")
    assert [e.label for e in Library(tmp_path / "data").entries()] == [DEFAULT_LABEL] * 3


def test_rename_folder_moves_all_its_series(lib, tmp_path):
    lib.assign(["2.25.1", "2.25.2"], "Case 01")
    assert lib.rename_folder("Case 01", "  Case A ") == 2
    assert lib.labels() == ["Case A", DEFAULT_LABEL]
    assert Library(tmp_path / "data").labels() == ["Case A", DEFAULT_LABEL]


def test_rename_unsorted_names_series_that_had_no_label(lib):
    assert lib.rename_folder(DEFAULT_LABEL, "Imported earlier") == 3
    assert lib.labels() == ["Imported earlier"]
