import dataclasses
import sqlite3
import time

import pytest

from cagsyntax.scoring import score_case
from cagsyntax.store import CaseStore, StoreError
from tests.scoring.builders import case, lesion

UID = "2.25.100"


@pytest.fixture
def store(tmp_path):
    s = CaseStore(tmp_path / "data" / "cases.sqlite")
    s.ensure_case(UID, "hash1")
    yield s
    s.close()


def form_and_result(*lesions, **kw):
    c = case(*lesions, **kw)
    return dataclasses.asdict(c), score_case(c)


def complete(seg="8"):
    return form_and_result(lesion(segments=[seg]))


def test_add_user_validates_and_is_unique_ignoring_case(store):
    ana = store.add_user("  Dr Ana ", "cardiologist")
    assert (ana.name, ana.level) == ("Dr Ana", "cardiologist")
    with pytest.raises(ValueError):
        store.add_user("dr ana", "resident")
    with pytest.raises(ValueError):
        store.add_user("Bob", "surgeon")
    with pytest.raises(ValueError):
        store.add_user("   ", "resident")
    assert [u.name for u in store.users()] == ["Dr Ana"]


def test_two_scorers_keep_separate_entries_and_one_scorer_updates(store):
    ana = store.add_user("Ana", "resident")
    ben = store.add_user("Ben", "resident")
    f1, r1 = complete("8")
    f2, r2 = complete("7")
    store.save_entry(UID, ana.id, f1, r1)
    store.save_entry(UID, ben.id, f2, r2)
    assert sorted(e.total for e in store.entries(UID)) == [2.0, 5.0]
    first = [e for e in store.entries(UID) if e.user.id == ana.id][0]
    time.sleep(0.01)
    store.save_entry(UID, ana.id, f2, r2)
    entries = store.entries(UID)
    assert len(entries) == 2
    updated = [e for e in entries if e.user.id == ana.id][0]
    assert updated.total == 5.0 and updated.saved_at > first.saved_at and updated.id == first.id


def test_resident_cannot_confirm_and_only_complete_own_case_entries_can(store):
    res = store.add_user("Res", "resident")
    card = store.add_user("Card", "cardiologist")
    f, r = complete()
    entry = store.save_entry(UID, res.id, f, r)
    with pytest.raises(PermissionError):
        store.confirm(UID, entry.id, res.id)
    f_inc, r_inc = form_and_result()
    inc = store.save_entry(UID, card.id, f_inc, r_inc)
    assert inc.status == "incomplete" and inc.total is None
    with pytest.raises(ValueError):
        store.confirm(UID, inc.id, card.id)
    store.ensure_case("2.25.200", "hash2")
    other = store.save_entry("2.25.200", card.id, f, r)
    with pytest.raises(ValueError):
        store.confirm(UID, other.id, card.id)
    assert store.confirmation(UID) is None


def test_cardiologist_confirms_and_a_later_confirmation_replaces(store):
    res = store.add_user("Res", "resident")
    card = store.add_user("Card", "cardiologist")
    f1, r1 = complete("8")
    f2, r2 = complete("7")
    e1 = store.save_entry(UID, res.id, f1, r1)
    e2 = store.save_entry(UID, card.id, f2, r2)
    c = store.confirm(UID, e1.id, card.id)
    assert (c.total, c.group, c.form, c.confirmed_by.name) == (2.0, "low", f1, "Card")
    store.confirm(UID, e2.id, card.id)
    assert store.confirmation(UID).total == 5.0
    assert [s for s in store.case_summaries() if s[0] == UID] == [(UID, 2, True)]


def test_confirmed_snapshot_is_not_changed_by_later_edits(store):
    card = store.add_user("Card", "cardiologist")
    f1, r1 = complete("8")
    f2, r2 = complete("7")
    e = store.save_entry(UID, card.id, f1, r1)
    store.confirm(UID, e.id, card.id)
    store.save_entry(UID, card.id, f2, r2)          # edit after confirming
    assert store.confirmation(UID).total == 2.0 and store.confirmation(UID).form == f1
    assert store.entries(UID)[0].total == 5.0


def test_form_round_trips_including_none_values(store):
    u = store.add_user("Ana", "resident")
    f, r = complete()
    store.save_entry(UID, u.id, f, r)
    assert store.entries(UID)[0].form == f
    assert store.entries(UID)[0].scoring_dominance == "right"


def test_meta_round_trip(store):
    assert store.get_meta("last_user_id") is None
    store.set_meta("last_user_id", "3")
    store.set_meta("last_user_id", "4")
    assert store.get_meta("last_user_id") == "4"


def test_ensure_case_is_idempotent(store):
    store.ensure_case(UID, "hash1")
    store.ensure_case(UID, "hash1")
    assert [s[0] for s in store.case_summaries()] == [UID]


def test_corrupt_database_gives_a_clear_error_and_is_not_modified(tmp_path):
    p = tmp_path / "cases.sqlite"
    p.write_bytes(b"this is not a database" * 50)
    before = p.read_bytes()
    with pytest.raises(StoreError, match="cases.sqlite"):
        CaseStore(p)
    assert p.read_bytes() == before


def test_database_from_a_newer_version_is_refused(tmp_path):
    p = tmp_path / "cases.sqlite"
    con = sqlite3.connect(p)
    con.execute("PRAGMA user_version = 99")
    con.execute("CREATE TABLE x(a)")
    con.commit()
    con.close()
    before = p.read_bytes()
    with pytest.raises(StoreError, match="newer"):
        CaseStore(p)
    assert p.read_bytes() == before


def test_missing_parent_folder_is_created(tmp_path):
    s = CaseStore(tmp_path / "a" / "b" / "cases.sqlite")
    s.close()
    assert (tmp_path / "a" / "b" / "cases.sqlite").exists()


def test_database_bytes_hold_no_patient_identifiers(store, tmp_path):
    u = store.add_user("Ana", "resident")
    f, r = complete()
    store.save_entry(UID, u.id, f, r)
    store.close()
    raw = (tmp_path / "data" / "cases.sqlite").read_bytes()
    for needle in (b"DOE", b"JOHN", b"MRN12345"):
        assert needle not in raw


def test_database_errors_after_opening_become_store_errors(tmp_path):
    p = tmp_path / "cases.sqlite"
    s = CaseStore(p, timeout=0.2)
    u = s.add_user("Ana", "resident")
    s.ensure_case(UID, "h")
    other = sqlite3.connect(p)
    other.execute("BEGIN EXCLUSIVE")
    f, r = complete()
    try:
        with pytest.raises(StoreError, match="locked"):
            s.save_entry(UID, u.id, f, r)
    finally:
        other.rollback()
        other.close()
        s.close()


def test_file_claiming_schema_1_but_without_tables_is_refused(tmp_path):
    p = tmp_path / "cases.sqlite"
    con = sqlite3.connect(p)
    con.execute("PRAGMA user_version = 1")
    con.commit()
    con.close()
    with pytest.raises(StoreError, match="cases.sqlite"):
        CaseStore(p)


def test_a_complete_result_without_a_total_is_rejected(store):
    from cagsyntax.scoring import CaseResult
    u = store.add_user("Ana", "resident")
    bad = CaseResult(status="complete", issues=[], total=None, group=None, dominance="right",
                     scoring_dominance="right", lesions=[])
    with pytest.raises(ValueError):
        store.save_entry(UID, u.id, {}, bad)
