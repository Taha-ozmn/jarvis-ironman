"""Postgres StorageBackend adapter (N-12) — optional; requires psycopg.

Default JarvisOS path remains SQLite. Enable via:

  jarvis2:
    storage:
      backend: postgres
      dsn: postgresql://user:pass@localhost:5432/jarvis

Without psycopg installed, open_backend raises a clear ImportError —
callers should keep SQLite as default.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

_QMARK = re.compile(r"\?")


class _MappingRow(dict):
    """dict subclass supporting both row['col'] and limited sqlite Row habits."""

    def __getitem__(self, key: Any) -> Any:  # type: ignore[override]
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class PostgresDatabase:
    """Minimal Postgres backend matching StorageBackend Protocol."""

    def __init__(self, dsn: str, *, display_path: Optional[str] = None) -> None:
        try:
            import psycopg  # type: ignore
            from psycopg.rows import dict_row  # type: ignore
        except ImportError as err:
            raise ImportError(
                "Postgres backend requires psycopg. "
                "Install: pip install 'psycopg[binary]' "
                "(see requirements-optional.txt)"
            ) from err

        self.path = Path(display_path or "postgresql://")
        self._dsn = dsn
        self._psycopg = psycopg
        self._dict_row = dict_row
        self._conn = psycopg.connect(dsn, row_factory=dict_row)
        self._conn.autocommit = False

    def _translate(self, sql: str) -> str:
        """SQLite '?' placeholders → psycopg '%s'."""
        return _QMARK.sub("%s", sql)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cur = self._conn.cursor()
        cur.execute(self._translate(sql), tuple(params))
        return cur

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> Any:
        cur = self._conn.cursor()
        cur.executemany(self._translate(sql), [tuple(p) for p in seq])
        return cur

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Optional[Any]:
        cur = self.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        return _MappingRow(row)

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[Any]:
        cur = self.execute(sql, params)
        return [_MappingRow(r) for r in cur.fetchall()]

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            logger.exception("postgres close failed")

    def migrate(self) -> list[str]:
        """Apply memory/migrations/*.sql with best-effort dialect (SQLite-first files).

        Returns applied migration names. Some SQLite-specific SQL may fail —
        those are logged and skipped so boot does not hard-crash; prefer SQLite
        for full migration fidelity until Postgres-native SQL exists.
        """
        from memory.database import MIGRATIONS_DIR

        self.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                applied_at TEXT NOT NULL
            )
            """
        )
        self.commit()
        applied: list[str] = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            name = path.name
            exists = self.fetchone(
                "SELECT 1 AS ok FROM schema_migrations WHERE name = ?",
                (name,),
            )
            if exists:
                continue
            sql = path.read_text(encoding="utf-8")
            # Best-effort: skip SQLite-only pragmas / FTS
            if "fts5" in sql.lower() or "pragma" in sql.lower():
                logger.warning("skipping sqlite-specific migration on postgres: %s", name)
                continue
            try:
                for stmt in sql.split(";"):
                    stmt = stmt.strip()
                    if not stmt:
                        continue
                    stmt = stmt.replace(
                        "INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY"
                    )
                    stmt = stmt.replace("AUTOINCREMENT", "")
                    self.execute(stmt)
                from datetime import datetime, timezone

                self.execute(
                    "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                    (name, datetime.now(timezone.utc).isoformat()),
                )
                self.commit()
                applied.append(name)
            except Exception:
                self._conn.rollback()
                logger.exception("postgres migration failed: %s", name)
        return applied
