"""Daily briefing from local tasks / memories / projects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from core.task_manager import TaskManager
from memory.database import Database
from memory.repository import MemoryRepository


@dataclass
class Briefing:
    voice: str
    detail: str


class BriefingGenerator:
    """Build a short voice line + optional detail from local SQLite data."""

    def __init__(
        self,
        tasks: TaskManager,
        memory: MemoryRepository,
        db: Database,
        *,
        user_name: str = "sir",
        language: str = "en",
    ) -> None:
        self.tasks = tasks
        self.memory = memory
        self.db = db
        self.user_name = user_name or "sir"
        self.language = "tr" if str(language).lower().startswith("tr") else "en"

    def generate(self) -> Briefing:
        pending = self.tasks.list(status="pending", limit=20)
        in_progress = self.tasks.list(status="in_progress", limit=10)
        overdue = self._overdue_tasks()
        prefs = self.memory.search("", category="preference", limit=3)
        projects = self._projects(limit=3)

        open_count = len(pending) + len(in_progress)
        overdue_count = len(overdue)

        if self.language == "tr":
            voice = self._voice_tr(open_count, overdue_count)
        else:
            voice = self._voice_en(open_count, overdue_count)

        detail_parts: list[str] = []
        if overdue:
            titles = ", ".join(t.title for t in overdue[:3])
            detail_parts.append(f"Overdue: {titles}")
        if pending:
            titles = ", ".join(t.title for t in pending[:5])
            detail_parts.append(f"Pending: {titles}")
        if projects:
            detail_parts.append("Projects: " + ", ".join(projects))
        if prefs:
            detail_parts.append(
                "Notes: " + "; ".join(m.content[:80] for m in prefs[:2])
            )
        detail = " | ".join(detail_parts) if detail_parts else "No open items."
        if len(detail) > 400:
            detail = detail[:400] + "…"
        return Briefing(voice=voice, detail=detail)

    def _voice_en(self, open_count: int, overdue_count: int) -> str:
        if open_count == 0 and overdue_count == 0:
            return f"Good day, {self.user_name}. No open tasks — systems clear."
        if overdue_count:
            return (
                f"Briefing, {self.user_name}: {overdue_count} overdue, "
                f"{open_count} open tasks."
            )
        return f"Briefing, {self.user_name}: {open_count} open tasks on the board."

    def _voice_tr(self, open_count: int, overdue_count: int) -> str:
        address = "efendim" if self.user_name in ("sir", "") else self.user_name
        if open_count == 0 and overdue_count == 0:
            return f"Günaydın {address}. Açık görev yok — sistemler hazır."
        if overdue_count:
            return (
                f"Brifing {address}: {overdue_count} gecikmiş, "
                f"{open_count} açık görev var."
            )
        return f"Brifing {address}: {open_count} açık göreviniz var."

    def _overdue_tasks(self) -> list[Any]:
        now = datetime.now(timezone.utc).isoformat()
        rows = self.db.fetchall(
            """
            SELECT * FROM tasks
            WHERE status IN ('pending', 'in_progress')
              AND due_at IS NOT NULL
              AND due_at < ?
            ORDER BY due_at ASC
            LIMIT 10
            """,
            (now,),
        )
        from core.task_manager import Task

        return [Task.from_row(r) for r in rows]

    def _projects(self, limit: int = 3) -> list[str]:
        rows = self.db.fetchall(
            "SELECT name FROM projects ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [str(r["name"]) for r in rows]
