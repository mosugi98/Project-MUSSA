import sqlite3

import pytest

from cagsyntax.store import SCHEMA_VERSION, AiRun, CaseStore, StoreError

UID = "2.25.100"
V2_EXTRA = """
CREATE TABLE suggestion_events(id INTEGER PRIMARY KEY, study_uid TEXT NOT NULL REFERENCES cases(study_uid),
                               user_id INTEGER NOT NULL REFERENCES users(id), series_uid TEXT NOT NULL,
                               frame INTEGER NOT NULL, segment TEXT, score REAL NOT NULL, pixels INTEGER NOT NULL,
                               action TEXT NOT NULL CHECK(action IN ('accepted','rejected')),
                               segment_model TEXT NOT NULL, stenosis_model TEXT NOT NULL, logged_at TEXT NOT NULL);
"""
V2_SCHEMA = """
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
""" + V2_EXTRA


@pytest.fixture
def store(tmp_path):
    s = CaseStore(tmp_path / "cases.sqlite")
    s.ensure_case(UID, "hash1")
    s.user = s.add_user("Ana", "resident")
    yield s
    s.close()


def test_schema_version_is_three():
    assert SCHEMA_VERSION == 3


def test_an_ai_run_round_trips_with_who_when_models_and_what_was_taken(store):
    run_id = store.log_ai_run(UID, store.user.id, '{"runs": []}', ["AI_6", "AI_11"], ["AI_6"],
                              "segments 2026-11-20 aaaa1111", "stenosis 2026-11-21 bbbb2222")
    got = store.ai_runs(UID)
    assert len(got) == 1 and isinstance(got[0], AiRun) and got[0].id == run_id
    assert got[0].payload_json == '{"runs": []}' and got[0].user_id == store.user.id and got[0].created_at
    assert got[0].proposed == ["AI_6", "AI_11"] and got[0].accepted == ["AI_6"]
    assert got[0].segment_model.endswith("aaaa1111") and got[0].stenosis_model.endswith("bbbb2222")


def test_runs_come_oldest_first_and_cases_are_kept_apart(store):
    store.ensure_case("2.25.200", "hash2")
    store.log_ai_run(UID, store.user.id, "{}", [], [], "s", "t")
    store.log_ai_run("2.25.200", store.user.id, "{}", ["AI_9"], [], "s", "t")
    store.log_ai_run(UID, store.user.id, '{"second": 1}', [], [], "s", "t")
    assert [r.payload_json for r in store.ai_runs(UID)] == ["{}", '{"second": 1}']
    assert [r.proposed for r in store.ai_runs("2.25.200")] == [["AI_9"]]


def test_accepting_something_that_was_not_proposed_is_refused_and_nothing_is_stored(store):
    with pytest.raises(ValueError):
        store.log_ai_run(UID, store.user.id, "{}", ["AI_6"], ["AI_11"], "s", "t")
    assert store.ai_runs(UID) == []


def test_a_run_for_an_unknown_case_is_refused(store):
    with pytest.raises(StoreError):
        store.log_ai_run("2.25.999", store.user.id, "{}", [], [], "s", "t")


def test_upgrading_a_v2_store_keeps_its_rows_and_a_backup(tmp_path):
    path = tmp_path / "cases.sqlite"
    con = sqlite3.connect(path)
    con.executescript(V2_SCHEMA)
    con.execute("INSERT INTO users(name, name_key, level) VALUES ('Ana', 'ana', 'resident')")
    con.execute("INSERT INTO cases VALUES ('2.25.1', 'h')")
    con.execute("PRAGMA user_version = 2")
    con.commit()
    con.close()
    s = CaseStore(path)
    try:
        assert [u.name for u in s.users()] == ["Ana"] and s.ai_runs("2.25.1") == []
        s.log_ai_run("2.25.1", s.users()[0].id, "{}", [], [], "s", "t")
        assert len(s.ai_runs("2.25.1")) == 1
    finally:
        s.close()
    backup = tmp_path / "cases.sqlite.v2.bak"
    assert backup.exists()
    old = sqlite3.connect(backup)
    try:
        assert old.execute("PRAGMA user_version").fetchone()[0] == 2
        assert old.execute("SELECT 1 FROM sqlite_master WHERE name='ai_runs'").fetchone() is None
    finally:
        old.close()


def test_a_v1_store_is_upgraded_all_the_way(tmp_path):
    path = tmp_path / "cases.sqlite"
    con = sqlite3.connect(path)
    con.executescript(V2_SCHEMA.replace(V2_EXTRA, ""))
    con.execute("PRAGMA user_version = 1")
    con.commit()
    con.close()
    s = CaseStore(path)
    try:
        assert s.ai_runs("x") == [] and s.suggestion_events("x") == []
        assert s._con.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        s.close()
