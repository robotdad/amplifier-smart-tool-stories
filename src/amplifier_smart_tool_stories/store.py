"""SQLite transactions serialize mutations across callers, viewers, and workers."""

import contextlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path


def identity(prefix):
    return prefix + "_" + uuid.uuid4().hex


def now():
    return time.time()


class Store:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.path / "stories.sqlite3"
        with self.transaction() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS provider_jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS narration_scripts (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS narration_renders (id TEXT PRIMARY KEY, data TEXT NOT NULL, video BLOB NOT NULL, audio BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS narration_settings (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS narrations (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS speech_audio (id TEXT PRIMARY KEY, data TEXT NOT NULL, content BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS speech_attempts (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS media (id TEXT PRIMARY KEY, metadata TEXT NOT NULL, content BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS stories (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT,
                story_id TEXT NOT NULL, data TEXT NOT NULL);
            """)
        os.chmod(self.db, 0o600)

    @contextlib.contextmanager
    def transaction(self):
        db = sqlite3.connect(self.db, timeout=30)
        try:
            db.execute("PRAGMA busy_timeout=30000")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def get(db, table, key):
        row = db.execute(f"SELECT data FROM {table} WHERE id=?", (key,)).fetchone()
        if row is None:
            from .errors import StoriesError

            raise StoriesError("not_found", f"No retained {table[:-1]} with that identity.")
        return json.loads(row[0])

    @staticmethod
    def put(db, table, value):
        db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?)", (value["id"], json.dumps(value)))

    @staticmethod
    def event(db, story_id, kind, **fields):
        db.execute(
            "INSERT INTO events(story_id,data) VALUES (?,?)",
            (story_id, json.dumps({"kind": kind, "at": now(), **fields})),
        )
