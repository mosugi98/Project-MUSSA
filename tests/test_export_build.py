import dataclasses
import json

import pytest

from cagsyntax.cases import study_of
from cagsyntax.export.dataset import Exclusion, ExportCase, ExportDataset, build_dataset
from cagsyntax.export.splits import suggest_split
from cagsyntax.library import Library
from cagsyntax.scoring import SOURCE, VERSION, score_case
from cagsyntax.store import CaseStore
from tests.scoring.builders import case, lesion
from tests.test_export_dataset import STUDY_A, STUDY_B, build, study_uids


@pytest.fixture
def world(tmp_path):
    """Library with study A (2 cines + 1 still) and study B (1 cine) plus a case store."""
    lib, src = build(tmp_path)
    store = CaseStore(tmp_path / "data" / "cases.sqlite")
    uids = sorted(study_uids(lib))
    by_count = {len([e for e in lib.entries() if study_of(e.path)[0] == u]): u for u in uids}
    yield lib, store, by_count[3], by_count[1], tmp_path
    store.close()


def confirm(store, uid, mrn_hash="hash-A", level="cardiologist", name="Dr Secret Name", form_case=None):
    card = next((u for u in store.users() if u.name == name), None) or store.add_user(name, level)
    store.ensure_case(uid, mrn_hash)
    c = form_case or case(lesion(segments=["7"]))
    entry = store.save_entry(uid, card.id, dataclasses.asdict(c), score_case(c))
    return store.confirm(uid, entry.id, card.id)


def test_confirmed_case_is_exported_with_reference_series_and_split(world):
    lib, store, uid_a, uid_b, _ = world
    confirm(store, uid_a)
    ds = build_dataset(store, lib)
    assert isinstance(ds, ExportDataset) and [c.case_id for c in ds.cases] == [uid_a] and ds.excluded == []
    c = ds.cases[0]
    assert isinstance(c, ExportCase)
    assert (c.patient_key, c.suggested_split) == ("hash-A", suggest_split("hash-A"))
    assert c.confirmed_by_level == "cardiologist" and c.confirmed_at
    assert c.reference["total"] == 5.0 and c.reference["group"] == "low"
    assert c.reference["dominance"] == "right" and c.reference["diffuse_segments"] == []
    assert c.reference["form"]["lesions"][0]["segments"] == ["7"]
    [les] = c.reference["lesions"]
    assert les["segments"] == ["7"] and sum(p["points"] for p in les["parts"]) == les["total"] == 5.0
    assert c.rescored == {"total": 5.0, "group": "low", "consistent": True}
    assert [s.kind for s in c.series] == ["cine", "cine"]                # stills excluded by default
    assert (ds.engine_source, ds.engine_version) == (SOURCE, VERSION) and ds.include_stills is False


def test_unconfirmed_cases_are_not_exported(world):
    lib, store, uid_a, uid_b, _ = world
    card = store.add_user("Card", "cardiologist")
    store.ensure_case(uid_b, "hash-B")
    c = case(lesion())
    store.save_entry(uid_b, card.id, dataclasses.asdict(c), score_case(c))   # saved, not confirmed
    assert build_dataset(store, lib).cases == []


def test_no_names_labels_or_original_uids_in_the_dataset(world):  # Review Focus 1
    lib, store, uid_a, _, _ = world
    lib.assign([e.uid for e in lib.entries()], "Patient John Doe case")
    confirm(store, uid_a)
    text = json.dumps(dataclasses.asdict(build_dataset(store, lib, include_stills=True)))
    for needle in ("Dr Secret Name", "Secret", "Patient John Doe", STUDY_A, STUDY_B, "secret_name", "DOE", "MRN12345"):
        assert needle not in text


def test_a_confirmed_case_without_series_is_excluded_with_a_reason(world):  # Review Focus 3
    lib, store, uid_a, uid_b, _ = world
    confirm(store, uid_a)
    confirm(store, uid_b, mrn_hash="hash-B")
    for e in lib.entries():
        if study_of(e.path)[0] == uid_a:
            lib.delete_series(e.uid)
    ds = build_dataset(store, lib)
    assert [c.case_id for c in ds.cases] == [uid_b]
    assert ds.excluded == [Exclusion(uid_a, ds.excluded[0].reason)] and "no series" in ds.excluded[0].reason


def test_engine_disagreement_is_flagged_not_hidden(world):  # Review Focus 4
    lib, store, uid_a, _, _ = world
    confirm(store, uid_a)
    store._con.execute("UPDATE confirmations SET total = 99.0, grp = 'high' WHERE study_uid = ?", (uid_a,))
    store._con.commit()
    c = build_dataset(store, lib).cases[0]
    assert c.reference["total"] == 99.0                                   # the confirmed snapshot is kept
    assert c.rescored["total"] == 5.0 and c.rescored["consistent"] is False


def test_study_with_only_a_still_is_excluded_by_default_and_included_on_request(world):  # Review Focus 5
    from cagsyntax.dicom_import.reader import read_header
    lib, store, uid_a, _, _ = world
    confirm(store, uid_a)
    for e in lib.entries():                                              # keep only the still of study A
        if study_of(e.path)[0] == uid_a and read_header(e.path).kind == "cine":
            lib.delete_series(e.uid)
    default = build_dataset(store, lib)
    assert default.cases == [] and "still" in default.excluded[0].reason
    included = build_dataset(store, lib, include_stills=True)
    assert [s.kind for s in included.cases[0].series] == ["still"] and included.include_stills is True


def test_stills_are_listed_after_cines_when_requested(world):
    lib, store, uid_a, _, _ = world
    confirm(store, uid_a)
    assert [s.kind for s in build_dataset(store, lib, include_stills=True).cases[0].series] == ["cine", "cine", "still"]


def test_a_confirmed_form_that_cannot_be_parsed_is_excluded_not_a_crash(world):
    lib, store, uid_a, _, _ = world
    confirm(store, uid_a)
    store._con.execute("UPDATE confirmations SET form_json = '{\"bad\": 1}' WHERE study_uid = ?", (uid_a,))
    store._con.commit()
    ds = build_dataset(store, lib)
    assert ds.cases == [] and len(ds.excluded) == 1 and "form" in ds.excluded[0].reason.lower()


def test_empty_store_gives_an_empty_dataset(world):
    lib, store, *_ = world
    ds = build_dataset(store, lib)
    assert ds.cases == [] and ds.excluded == []


def test_dataset_is_deterministic_apart_from_the_created_time(world):
    lib, store, uid_a, uid_b, _ = world
    confirm(store, uid_a)
    confirm(store, uid_b, mrn_hash="hash-B")
    a, b = (dataclasses.asdict(build_dataset(store, lib)) for _ in range(2))
    a.pop("created"), b.pop("created")
    assert a == b
