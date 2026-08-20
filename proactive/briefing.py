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
        user_name: str = "",
        language: str = "en",
    ) -> None:
        self.tasks = tasks
        self.memory = memory
        self.db = db
        self.user_name = (user_name or "").strip()
        self.language = "en" if not str(language).lower().startswith("tr") else "tr"

    def generate(self) -> Briefing:
        pending = self.tasks.list(status="pending", limit=20)
        in_progress = self.tasks.list(status="in_progress", limit=10)
        overdue = self._overdue_tasks()
        prefs = self.memory.search("", category="preference", limit=3)
        projects = self._projects(limit=3)

        open_count = len(pending) + len(in_progress)
        overdue_count = len(overdue)

        voice = self._voice_line(open_count, overdue_count)

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
        detail = " | ".join(detail_parts) if detail_parts else "Nothing outstanding."
        if len(detail) > 400:
            detail = detail[:400] + "…"
        return Briefing(voice=voice, detail=detail)

    def _voice_line(self, open_count: int, overdue_count: int) -> str:
        name = self.user_name if self.user_name and self.user_name.lower() not in (
            "sir",
            "efendim",
        ) else ""
        if str(self.language).lower().startswith("tr"):
            greet = f"Günaydın{(' ' + name) if name else ''}."
            if open_count == 0 and overdue_count == 0:
                return f"{greet} Açık görev yok — sistemler hazır."
            if overdue_count:
                prefix = f"Brifing{(' ' + name) if name else ''}"
                return (
                    f"{prefix}: {overdue_count} gecikmiş, "
                    f"{open_count} açık görev var."
                )
            prefix = f"Brifing{(' ' + name) if name else ''}"
            return f"{prefix}: {open_count} açık göreviniz var."
        greet = f"Good morning{(' ' + name) if name else ''}."
        if open_count == 0 and overdue_count == 0:
            return f"{greet} No open tasks — systems ready."
        if overdue_count:
            prefix = f"Briefing{(' ' + name) if name else ''}"
            return (
                f"{prefix}: {overdue_count} overdue, "
                f"{open_count} open tasks."
            )
        prefix = f"Briefing{(' ' + name) if name else ''}"
        return f"{prefix}: you have {open_count} open tasks."

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
