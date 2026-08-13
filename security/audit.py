"""Audit log — SQLite-backed security / action trail."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
import json

from memory.database import Database


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AuditEntry:
    id: int
    action: str
    level: int
    success: bool
    details: str
    created_at: str


class AuditLog:
    def __init__(self, db: Database) -> None:
        self._db = db

    def write(
        self,
        *,
        action: str,
        level: int = 0,
        success: bool = True,
        details: Optional[dict[str, Any]] = None,
    ) -> int:
        payload = json.dumps(details or {}, ensure_ascii=False, default=str)
        cursor = self._db.execute(
            """
            INSERT INTO audit_logs (action, level, success, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (action, int(level), 1 if success else 0, payload, _utc_now()),
        )
        self._db.commit()
        return int(cursor.lastrowid)

    def recent(self, limit: int = 50) -> list[AuditEntry]:
        rows = self._db.fetchall(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [
            AuditEntry(
                id=r["id"],
                action=r["action"],
                level=r["level"],
                success=bool(r["success"]),
                details=r["details"] or "{}",
                created_at=r["created_at"],
            )
            for r in rows
        ]
