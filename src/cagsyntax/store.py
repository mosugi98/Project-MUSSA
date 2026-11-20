from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .scoring import VERSION, CaseResult

SCHEMA_VERSION = 1
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
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class CaseStore:
    """SQLite store of scorers, cases (studies), one entry per scorer and case, and the
    confirmed reference snapshot of each case. Holds no direct patient identifiers."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._con = sqlite3.connect(self.path)
            self._con.execute("PRAGMA foreign_keys = ON")
            version = self._con.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                self._con.close()
                raise StoreError(f"{self.path.name} was written by a newer version of MUSSA "
                                 f"(schema {version}); update the app to open it.")
            if version == 0:
                with self._con:
                    self._con.executescript(_SCHEMA)
                    self._con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except sqlite3.DatabaseError as exc:
            raise StoreError(f"Cannot open {self.path.name}: {exc}. The file may be damaged; "
                             f"it was not changed.") from exc

    def close(self) -> None:
        self._con.close()

    # ---- users ----
    def _user(self, row) -> User:
        return User(id=row[0], name=row[1], level=row[2])

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

    def users(self) -> list[User]:
        rows = self._con.execute("SELECT id, name, level FROM users ORDER BY name_key").fetchall()
        return [self._user(r) for r in rows]

    def _get_user(self, user_id: int) -> User:
        row = self._con.execute("SELECT id, name, level FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown scorer id {user_id}.")
        return self._user(row)

    # ---- cases and entries ----
    def ensure_case(self, study_uid: str, mrn_hash: str) -> None:
        with self._con:
            self._con.execute("INSERT OR IGNORE INTO cases(study_uid, mrn_hash) VALUES (?,?)",
                              (study_uid, mrn_hash))

    def save_entry(self, study_uid: str, user_id: int, form: dict, result: CaseResult) -> Entry:
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

    def entries(self, study_uid: str) -> list[Entry]:
        rows = self._con.execute(
            "SELECT e.id, e.study_uid, u.id, u.name, u.level, e.form_json, e.status, e.total, e.grp, "
            "e.scoring_dominance, e.saved_at FROM entries e JOIN users u ON u.id = e.user_id "
            "WHERE e.study_uid=? ORDER BY e.id", (study_uid,)).fetchall()
        return [Entry(r[0], r[1], User(r[2], r[3], r[4]), json.loads(r[5]), r[6], r[7], r[8], r[9], r[10])
                for r in rows]

    # ---- confirmation ----
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

    def confirmation(self, study_uid: str) -> Confirmation | None:
        row = self._con.execute(
            "SELECT c.entry_id, u.id, u.name, u.level, c.confirmed_at, c.form_json, c.status, c.total, "
            "c.grp FROM confirmations c JOIN users u ON u.id = c.confirmed_by WHERE c.study_uid=?",
            (study_uid,)).fetchone()
        if row is None:
            return None
        return Confirmation(row[0], User(row[1], row[2], row[3]), row[4], json.loads(row[5]), row[6],
                            row[7], row[8])

    def case_summaries(self) -> list[tuple[str, int, bool]]:
        rows = self._con.execute(
            "SELECT c.study_uid, (SELECT COUNT(*) FROM entries e WHERE e.study_uid=c.study_uid), "
            "EXISTS(SELECT 1 FROM confirmations f WHERE f.study_uid=c.study_uid) "
            "FROM cases c ORDER BY c.study_uid").fetchall()
        return [(r[0], r[1], bool(r[2])) for r in rows]

    # ---- small settings ----
    def get_meta(self, key: str) -> str | None:
        row = self._con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._con:
            self._con.execute("INSERT INTO meta(key, value) VALUES (?,?) "
                              "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
