"""SQLite database wrapper with simple SQL migrations."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class Database:
    """Thread-local SQLite connections to one file."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

    def connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            self._local.conn = conn
        return conn

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        return self.connect().execute(sql, params)

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
        return self.connect().executemany(sql, seq)

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Optional[sqlite3.Row]:
        return self.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return list(self.execute(sql, params).fetchall())

    def commit(self) -> None:
        self.connect().commit()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def migrate(self) -> list[str]:
        """Apply pending *.sql migrations in sorted order. Returns applied names."""
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                applied_at TEXT NOT NULL
            )
            """
        )
        self.commit()
        applied: list[str] = []
        files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        for path in files:
            name = path.name
            exists = self.fetchone(
                "SELECT 1 AS ok FROM schema_migrations WHERE name = ?",
                (name,),
            )
            if exists:
                continue
            sql = path.read_text(encoding="utf-8")
            self.connect().executescript(sql)
            from datetime import datetime, timezone

            self.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (name, datetime.now(timezone.utc).isoformat()),
            )
            self.commit()
            applied.append(name)
        return applied
