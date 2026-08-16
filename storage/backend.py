"""Storage backend Protocol — SQLite today, Postgres-ready seam (Phase 14).

JarvisOS still constructs `memory.database.Database`. Callers that need
backend-agnostic typing can depend on `StorageBackend` instead of the
concrete class. A future Postgres adapter implements the same surface.
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


def backend_kind(db: Any) -> str:
    """Honest label for diagnostics / health."""
    name = type(db).__name__
    module = type(db).__module__
    if "postgres" in module.lower() or "postgres" in name.lower():
        return "postgres"
    if "sqlite" in module.lower() or name == "Database":
        return "sqlite"
    return name or "unknown"
