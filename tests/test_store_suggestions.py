import sqlite3

import pytest

from cagsyntax.store import SCHEMA_VERSION, CaseStore, StoreError, SuggestionEvent

UID = "2.25.100"

V1_SCHEMA = """
CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, level TEXT NOT NULL);
CREATE TABLE cases(study_uid TEXT PRIMARY KEY, mrn_hash TEXT NOT NULL);
CREATE TABLE entries(id INTEGER PRIMARY KEY, study_uid TEXT NOT NULL REFERENCES cases(study_uid),
                     user_id INTEGER NOT NULL REFERENCES users(id), form_json TEXT NOT NULL,
                     status TEXT NOT NULL, total REAL, grp TEXT, scoring_dominance TEXT,
                     engine_version TEXT NOT NULL, saved_at TEXT NOT NULL, UNIQUE(study_uid, user_id));
CREATE TABLE confirmations(study_uid TEXT PRIMARY KEY REFERENCES cases(study_uid),
                           entry_id INTEGER NOT NULL, confirmed_by INTEGER NOT NULL REFERENCES users(id),
                           confirmed_at TEXT NOT NULL, form_json TEXT NOT NULL, status TEXT NOT NULL,
                           total REAL, grp TEXT);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def event(**kw) -> SuggestionEvent:
    base = dict(series_uid="2.25.7", frame=3, segment="6", score=0.82, pixels=140, action="accepted",
                segment_model="segments 2026-11-20", stenosis_model="stenosis 2026-11-21")
    base.update(kw)
    return SuggestionEvent(**base)


@pytest.fixture
def store(tmp_path):
    s = CaseStore(tmp_path / "cases.sqlite")
    s.ensure_case(UID, "hash1")
    s.user = s.add_user("Ana", "resident")
    yield s
    s.close()


def test_schema_version_is_two():
    assert SCHEMA_VERSION == 2


def test_events_round_trip_in_order_with_who_and_when(store):
    store.log_suggestions(UID, store.user.id, [event(), event(segment="11", score=0.5, action="rejected")])
    got = store.suggestion_events(UID)
    assert [(e.segment, e.action, e.score) for e in got] == [("6", "accepted", 0.82), ("11", "rejected", 0.5)]
    assert got[0].user_id == store.user.id and got[0].frame == 3 and got[0].pixels == 140
    assert got[0].segment_model == "segments 2026-11-20" and got[0].logged_at


def test_an_unplaced_suggestion_can_be_logged_with_no_segment(store):
    store.log_suggestions(UID, store.user.id, [event(segment=None, action="rejected")])
    assert store.suggestion_events(UID)[0].segment is None


def test_events_of_other_cases_are_kept_apart(store):
    store.ensure_case("2.25.200", "hash2")
    store.log_suggestions(UID, store.user.id, [event()])
    store.log_suggestions("2.25.200", store.user.id, [event(segment="9")])
    assert [e.segment for e in store.suggestion_events(UID)] == ["6"]
    assert [e.segment for e in store.suggestion_events("2.25.200")] == ["9"]


def test_logging_nothing_is_fine(store):
    store.log_suggestions(UID, store.user.id, [])
    assert store.suggestion_events(UID) == []


def test_an_unknown_action_is_refused_and_nothing_is_written(store):
    with pytest.raises(ValueError):
        store.log_suggestions(UID, store.user.id, [event(), event(action="ignored")])
    assert store.suggestion_events(UID) == []


def test_a_case_or_scorer_that_does_not_exist_is_a_clear_store_error(store):
    with pytest.raises(StoreError):
        store.log_suggestions("2.25.999", store.user.id, [event()])
    with pytest.raises(StoreError):
        store.log_suggestions(UID, 9999, [event()])
    assert store.suggestion_events(UID) == []


def test_a_failed_write_leaves_no_partial_batch(store):
    with pytest.raises(StoreError):
        store.log_suggestions(UID, store.user.id, [event(), event(score=None)])      # the second row breaks a NOT NULL rule
    assert store.suggestion_events(UID) == []                                         # the first was rolled back too


def test_a_version_one_database_is_upgraded_and_keeps_its_data(tmp_path):
    path = tmp_path / "cases.sqlite"
    con = sqlite3.connect(path)
    con.executescript(V1_SCHEMA)
    con.execute("INSERT INTO users(name, name_key, level) VALUES('Ana', 'ana', 'cardiologist')")
    con.execute("INSERT INTO cases VALUES('2.25.1', 'h')")
    con.execute("PRAGMA user_version = 1")
    con.commit()
    con.close()
    store = CaseStore(path)
    try:
        assert [u.name for u in store.users()] == ["Ana"]
        store.log_suggestions("2.25.1", store.users()[0].id, [event()])
        assert len(store.suggestion_events("2.25.1")) == 1
    finally:
        store.close()
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == 2


def test_a_new_database_is_created_at_version_two(tmp_path):
    CaseStore(tmp_path / "x.sqlite").close()
    assert sqlite3.connect(tmp_path / "x.sqlite").execute("PRAGMA user_version").fetchone()[0] == 2


def test_a_database_from_a_newer_version_is_still_refused(tmp_path):
    path = tmp_path / "cases.sqlite"
    con = sqlite3.connect(path)
    con.execute("PRAGMA user_version = 3")
    con.close()
    with pytest.raises(StoreError):
        CaseStore(path)
