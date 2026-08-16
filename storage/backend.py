"""Storage backend Protocol — SQLite today, Postgres-ready seam (Phase 14).

JarvisOS uses `open_backend(j2)` so the concrete engine is config-driven.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional, Protocol, Sequence, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    path: Path

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any: ...

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> Any: ...

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Optional[Any]: ...

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[Any]: ...

    def commit(self) -> None: ...

    def close(self) -> None: ...

    def migrate(self) -> None: ...


def open_sqlite(path: Path | str) -> StorageBackend:
    """Factory — default production/dev backend."""
    from memory.database import Database

    return Database(path)


def open_backend(
    j2: Optional[dict[str, Any]] = None,
    *,
    default_sqlite_path: Path | str = "data/jarvis.db",
) -> StorageBackend:
    """Open storage from jarvis2 config.

    ```yaml
    jarvis2:
      db_path: data/jarvis.db          # sqlite (default)
      storage:
        backend: sqlite | postgres
        dsn: postgresql://...          # required for postgres
    ```
    """
    cfg = j2 or {}
    storage = cfg.get("storage") or {}
    kind = str(storage.get("backend") or "sqlite").strip().lower()
    if kind in ("postgres", "postgresql", "pg"):
        dsn = str(storage.get("dsn") or "").strip()
        if not dsn:
            raise ValueError("jarvis2.storage.dsn required when backend=postgres")
        from storage.postgres import PostgresDatabase

        return PostgresDatabase(dsn, display_path=dsn.split("@")[-1] if "@" in dsn else "postgres")
    path = cfg.get("db_path") or storage.get("path") or default_sqlite_path
    return open_sqlite(path)


def backend_kind(db: Any) -> str:
    """Honest label for diagnostics / health."""
    name = type(db).__name__
    module = type(db).__module__
    if "postgres" in module.lower() or "postgres" in name.lower():
        return "postgres"
    if "sqlite" in module.lower() or name == "Database":
        return "sqlite"
    return name or "unknown"
