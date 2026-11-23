from __future__ import annotations

import functools
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .scoring import VERSION, CaseResult

SCHEMA_VERSION = 3
SUGGESTION_ACTIONS = ("accepted", "rejected")
LEVELS = ("resident", "cardiologist")


class StoreError(Exception):
    """The case store cannot be opened or used. The message is shown to the user."""


@dataclass
class User:
    id: int
    name: str
    level: str


@dataclass
class Entry:
    id: int
    study_uid: str
    user: User
    form: dict
    status: str
    total: float | None
    group: str | None
    scoring_dominance: str | None
    saved_at: str


@dataclass
class Confirmation:
    entry_id: int
    confirmed_by: User
    confirmed_at: str
    form: dict
    status: str
    total: float | None
    group: str | None


@dataclass
class SuggestionEvent:
    """One AI suggestion the scorer accepted or rejected. `user_id` and `logged_at` are filled in when read."""
    series_uid: str
    frame: int
    segment: str | None
    score: float
    pixels: int
    action: str
    segment_model: str
    stenosis_model: str
    user_id: int | None = None
    logged_at: str | None = None


@dataclass
class AiRun:
    """What the AI proposed for a whole study, exactly as it produced it (`payload_json`), and which of the
    proposed lesions the scorer took into the form. The scorer's final answer is the entry, never this."""
    id: int
    study_uid: str
    user_id: int
    payload_json: str
    proposed: list[str]
    accepted: list[str]
    segment_model: str
    stenosis_model: str
    created_at: str


@dataclass
class ConfirmedCase:
    study_uid: str
    mrn_hash: str
    confirmation: Confirmation


_SCHEMA = """
CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
                   level TEXT NOT NULL);
CREATE TABLE cases(study_uid TEXT PRIMARY KEY, mrn_hash TEXT NOT NULL);
CREATE TABLE entries(id INTEGER PRIMARY KEY, study_uid TEXT NOT NULL REFERENCES cases(study_uid),
                     user_id INTEGER NOT NULL REFERENCES users(id), form_json TEXT NOT NULL,
                     status TEXT NOT NULL, total REAL, grp TEXT, scoring_dominance TEXT,
                     engine_version TEXT NOT NULL, saved_at TEXT NOT NULL,
                     UNIQUE(study_uid, user_id));
CREATE TABLE confirmations(study_uid TEXT PRIMARY KEY REFERENCES cases(study_uid),
                           entry_id INTEGER NOT NULL, confirmed_by INTEGER NOT NULL REFERENCES users(id),
                           confirmed_at TEXT NOT NULL, form_json TEXT NOT NULL, status TEXT NOT NULL,
                           total REAL, grp TEXT);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
""" + """
CREATE TABLE suggestion_events(id INTEGER PRIMARY KEY, study_uid TEXT NOT NULL REFERENCES cases(study_uid),
                               user_id INTEGER NOT NULL REFERENCES users(id), series_uid TEXT NOT NULL,
                               frame INTEGER NOT NULL, segment TEXT, score REAL NOT NULL, pixels INTEGER NOT NULL,
                               action TEXT NOT NULL CHECK(action IN ('accepted','rejected')),
                               segment_model TEXT NOT NULL, stenosis_model TEXT NOT NULL, logged_at TEXT NOT NULL);
""" + """
CREATE TABLE ai_runs(id INTEGER PRIMARY KEY, study_uid TEXT NOT NULL REFERENCES cases(study_uid),
                     user_id INTEGER NOT NULL REFERENCES users(id), payload_json TEXT NOT NULL,
                     proposed_json TEXT NOT NULL, accepted_json TEXT NOT NULL,
                     segment_model TEXT NOT NULL, stenosis_model TEXT NOT NULL, created_at TEXT NOT NULL);
"""
_V2_TO_V3 = """
CREATE TABLE IF NOT EXISTS ai_runs(id INTEGER PRIMARY KEY, study_uid TEXT NOT NULL REFERENCES cases(study_uid),
                     user_id INTEGER NOT NULL REFERENCES users(id), payload_json TEXT NOT NULL,
                     proposed_json TEXT NOT NULL, accepted_json TEXT NOT NULL,
                     segment_model TEXT NOT NULL, stenosis_model TEXT NOT NULL, created_at TEXT NOT NULL);
"""
_V1_TO_V2 = """
CREATE TABLE IF NOT EXISTS suggestion_events(id INTEGER PRIMARY KEY, study_uid TEXT NOT NULL REFERENCES cases(study_uid),
                               user_id INTEGER NOT NULL REFERENCES users(id), series_uid TEXT NOT NULL,
                               frame INTEGER NOT NULL, segment TEXT, score REAL NOT NULL, pixels INTEGER NOT NULL,
                               action TEXT NOT NULL CHECK(action IN ('accepted','rejected')),
                               segment_model TEXT NOT NULL, stenosis_model TEXT NOT NULL, logged_at TEXT NOT NULL);
"""


def _guarded(fn):
    """Turn sqlite errors (locked file, full disk, damaged file) into a clear StoreError."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except sqlite3.Error as exc:
            raise StoreError(f"{self.path.name}: {exc}. Nothing was changed.") from exc
    return wrapper


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class CaseStore:
    """SQLite store of scorers, cases (studies), one entry per scorer and case, and the
    confirmed reference snapshot of each case. Holds no direct patient identifiers."""

    def __init__(self, path: Path, timeout: float = 5.0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con = None
        try:
            self._con = sqlite3.connect(self.path, timeout=timeout)
            self._con.execute("PRAGMA foreign_keys = ON")
            version = self._con.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise StoreError(f"{self.path.name} was written by a newer version of MUSSA "
                                 f"(schema {version}); update the app to open it.")
            if version == 0:
                with self._con:
                    self._con.executescript(_SCHEMA)
                    self._con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif self._con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='entries'"
                                   ).fetchone() is None:
                raise StoreError(f"{self.path.name} is damaged (its tables are missing); "
                                 f"it was not changed.")
            elif version < SCHEMA_VERSION:
                backup = self.path.with_name(f"{self.path.name}.v{version}.bak")
                if not backup.exists():                  # keep the pre-upgrade copy: an older MUSSA can still open it
                    copy = sqlite3.connect(backup)
                    try:
                        self._con.backup(copy)
                    finally:
                        copy.close()
                with self._con:                          # upgrade in place; existing rows are untouched
                    self._con.executescript(_V1_TO_V2 + _V2_TO_V3)
                    self._con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except sqlite3.DatabaseError as exc:
            self.close()
            raise StoreError(f"Cannot open {self.path.name}: {exc}. The file may be damaged; "
                             f"it was not changed.") from exc
        except StoreError:
            self.close()
            raise

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    # ---- users ----
    def _user(self, row) -> User:
        return User(id=row[0], name=row[1], level=row[2])

    @_guarded
    def add_user(self, name: str, level: str) -> User:
        name = name.strip()
        if not name:
            raise ValueError("A scorer needs a name.")
        if level not in LEVELS:
            raise ValueError(f"Level must be one of {', '.join(LEVELS)}.")
        try:
            with self._con:
                cur = self._con.execute("INSERT INTO users(name, name_key, level) VALUES (?,?,?)",
                                        (name, name.casefold(), level))
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"A scorer named {name!r} already exists.") from exc
        return User(cur.lastrowid, name, level)

    @_guarded
    def users(self) -> list[User]:
        rows = self._con.execute("SELECT id, name, level FROM users ORDER BY name_key").fetchall()
        return [self._user(r) for r in rows]

    @_guarded
    def _get_user(self, user_id: int) -> User:
        row = self._con.execute("SELECT id, name, level FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown scorer id {user_id}.")
        return self._user(row)

    # ---- cases and entries ----
    @_guarded
    def ensure_case(self, study_uid: str, mrn_hash: str) -> None:
        with self._con:
            self._con.execute("INSERT OR IGNORE INTO cases(study_uid, mrn_hash) VALUES (?,?)",
                              (study_uid, mrn_hash))

    @_guarded
    def save_entry(self, study_uid: str, user_id: int, form: dict, result: CaseResult) -> Entry:
        if result.status == "complete" and result.total is None:
            raise ValueError("A complete score must have a total.")
        self._get_user(user_id)
        try:
            with self._con:
                self._con.execute(
                    "INSERT INTO entries(study_uid, user_id, form_json, status, total, grp, "
                    "scoring_dominance, engine_version, saved_at) VALUES (?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(study_uid, user_id) DO UPDATE SET form_json=excluded.form_json, "
                    "status=excluded.status, total=excluded.total, grp=excluded.grp, "
                    "scoring_dominance=excluded.scoring_dominance, "
                    "engine_version=excluded.engine_version, saved_at=excluded.saved_at",
                    (study_uid, user_id, json.dumps(form), result.status, result.total, result.group,
                     result.scoring_dominance, VERSION, _now()))
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Unknown case {study_uid!r}.") from exc
        return next(e for e in self.entries(study_uid) if e.user.id == user_id)

    @_guarded
    def entries(self, study_uid: str) -> list[Entry]:
        rows = self._con.execute(
            "SELECT e.id, e.study_uid, u.id, u.name, u.level, e.form_json, e.status, e.total, e.grp, "
            "e.scoring_dominance, e.saved_at FROM entries e JOIN users u ON u.id = e.user_id "
            "WHERE e.study_uid=? ORDER BY e.id", (study_uid,)).fetchall()
        return [Entry(r[0], r[1], User(r[2], r[3], r[4]), json.loads(r[5]), r[6], r[7], r[8], r[9], r[10])
                for r in rows]

    # ---- confirmation ----
    @_guarded
    def confirm(self, study_uid: str, entry_id: int, user_id: int) -> Confirmation:
        user = self._get_user(user_id)
        if user.level != "cardiologist":
            raise PermissionError("Only a cardiologist can confirm a reference score.")
        entry = next((e for e in self.entries(study_uid) if e.id == entry_id), None)
        if entry is None:
            raise ValueError("That entry does not belong to this case.")
        if entry.status != "complete":
            raise ValueError("Only a complete score can be confirmed.")
        with self._con:
            self._con.execute(
                "INSERT OR REPLACE INTO confirmations(study_uid, entry_id, confirmed_by, confirmed_at, "
                "form_json, status, total, grp) VALUES (?,?,?,?,?,?,?,?)",
                (study_uid, entry.id, user.id, _now(), json.dumps(entry.form), entry.status,
                 entry.total, entry.group))
        return self.confirmation(study_uid)

    @_guarded
    def confirmation(self, study_uid: str) -> Confirmation | None:
        row = self._con.execute(
            "SELECT c.entry_id, u.id, u.name, u.level, c.confirmed_at, c.form_json, c.status, c.total, "
            "c.grp FROM confirmations c JOIN users u ON u.id = c.confirmed_by WHERE c.study_uid=?",
            (study_uid,)).fetchone()
        if row is None:
            return None
        return Confirmation(row[0], User(row[1], row[2], row[3]), row[4], json.loads(row[5]), row[6],
                            row[7], row[8])

    @_guarded
    def confirmed_cases(self) -> list[ConfirmedCase]:
        """Every case that has a confirmed reference, ordered by study uid."""
        rows = self._con.execute(
            "SELECT c.study_uid, c.mrn_hash FROM cases c JOIN confirmations f ON f.study_uid = c.study_uid "
            "ORDER BY c.study_uid").fetchall()
        return [ConfirmedCase(uid, mrn_hash, self.confirmation(uid)) for uid, mrn_hash in rows]

    @_guarded
    def case_summaries(self) -> list[tuple[str, int, bool]]:
        rows = self._con.execute(
            "SELECT c.study_uid, (SELECT COUNT(*) FROM entries e WHERE e.study_uid=c.study_uid), "
            "EXISTS(SELECT 1 FROM confirmations f WHERE f.study_uid=c.study_uid) "
            "FROM cases c ORDER BY c.study_uid").fetchall()
        return [(r[0], r[1], bool(r[2])) for r in rows]

    # ---- small settings ----
    @_guarded
    def scoring_status(self) -> dict[str, tuple[int, int, bool]]:
        """Per case: (complete entries, draft entries, has a confirmed reference)."""
        rows = self._con.execute(
            "SELECT c.study_uid, COALESCE(SUM(e.status = 'complete'), 0), "
            "COALESCE(SUM(e.status != 'complete'), 0), "
            "EXISTS(SELECT 1 FROM confirmations f WHERE f.study_uid = c.study_uid) "
            "FROM cases c LEFT JOIN entries e ON e.study_uid = c.study_uid GROUP BY c.study_uid").fetchall()
        return {r[0]: (int(r[1]), int(r[2]), bool(r[3])) for r in rows}

    @_guarded
    def log_suggestions(self, study_uid: str, user_id: int, events: list[SuggestionEvent]) -> None:
        """Record which AI suggestions the scorer accepted or rejected (one batch, all or nothing)."""
        for e in events:
            if e.action not in SUGGESTION_ACTIONS:
                raise ValueError(f"A suggestion action must be one of {', '.join(SUGGESTION_ACTIONS)}, not {e.action!r}.")
        if not events:
            return
        now = _now()
        with self._con:
            self._con.executemany(
                "INSERT INTO suggestion_events(study_uid, user_id, series_uid, frame, segment, score, pixels, "
                "action, segment_model, stenosis_model, logged_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(study_uid, user_id, e.series_uid, e.frame, e.segment, e.score, e.pixels, e.action,
                  e.segment_model, e.stenosis_model, now) for e in events])

    @_guarded
    def suggestion_events(self, study_uid: str) -> list[SuggestionEvent]:
        rows = self._con.execute(
            "SELECT series_uid, frame, segment, score, pixels, action, segment_model, stenosis_model, user_id, "
            "logged_at FROM suggestion_events WHERE study_uid=? ORDER BY id", (study_uid,)).fetchall()
        return [SuggestionEvent(*row) for row in rows]

    @_guarded
    def log_ai_run(self, study_uid: str, user_id: int, payload_json: str, proposed: list[str],
                   accepted: list[str], segment_model: str, stenosis_model: str) -> int:
        """Keep the AI's raw proposal for a study and which of its lesions the scorer took. Returns the run id."""
        if not set(accepted) <= set(proposed):
            raise ValueError("The accepted lesions must all be among the proposed ones: "
                             f"{sorted(set(accepted) - set(proposed))} were not proposed.")
        with self._con:
            cur = self._con.execute(
                "INSERT INTO ai_runs(study_uid, user_id, payload_json, proposed_json, accepted_json, segment_model, "
                "stenosis_model, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (study_uid, user_id, payload_json, json.dumps(list(proposed)), json.dumps(list(accepted)),
                 segment_model, stenosis_model, _now()))
        return int(cur.lastrowid)

    @_guarded
    def ai_runs(self, study_uid: str) -> list[AiRun]:
        rows = self._con.execute(
            "SELECT id, study_uid, user_id, payload_json, proposed_json, accepted_json, segment_model, "
            "stenosis_model, created_at FROM ai_runs WHERE study_uid=? ORDER BY id", (study_uid,)).fetchall()
        return [AiRun(r[0], r[1], r[2], r[3], json.loads(r[4]), json.loads(r[5]), r[6], r[7], r[8]) for r in rows]

    @_guarded
    def get_meta(self, key: str) -> str | None:
        row = self._con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    @_guarded
    def set_meta(self, key: str, value: str) -> None:
        with self._con:
            self._con.execute("INSERT INTO meta(key, value) VALUES (?,?) "
                              "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
