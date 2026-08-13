"""Task CRUD manager backed by SQLite."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from memory.database import Database


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Task:
    id: int
    title: str
    status: str
    priority: int
    description: str
    project_id: Optional[int]
    created_at: str
    updated_at: str
    due_at: Optional[str] = None
    metadata: str = "{}"

    @classmethod
    def from_row(cls, row: Any) -> "Task":
        return cls(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            priority=row["priority"],
            description=row["description"] or "",
            project_id=row["project_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            due_at=row["due_at"],
            metadata=row["metadata"] or "{}",
        )


class TaskManager:
    """Persist and query user tasks."""

    VALID_STATUSES = frozenset({"pending", "in_progress", "done", "cancelled"})

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        title: str,
        *,
        description: str = "",
        priority: int = 1,
        project_id: Optional[int] = None,
        due_at: Optional[str] = None,
        metadata: str = "{}",
    ) -> Task:
        title = title.strip()
        if not title:
            raise ValueError("Task title is required")
        now = _utc_now()
        cursor = self._db.execute(
            """
            INSERT INTO tasks
                (title, description, status, priority, project_id, due_at, metadata, created_at, updated_at)
            VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?)
            """,
            (title, description, priority, project_id, due_at, metadata, now, now),
        )
        self._db.commit()
        return self.get(int(cursor.lastrowid))

    def get(self, task_id: int) -> Task:
        row = self._db.fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if row is None:
            raise KeyError(f"Task not found: {task_id}")
        return Task.from_row(row)

    def update(
        self,
        task_id: int,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[int] = None,
        due_at: Optional[str] = None,
    ) -> Task:
        task = self.get(task_id)
        if status is not None and status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        new_title = title if title is not None else task.title
        new_desc = description if description is not None else task.description
        new_status = status if status is not None else task.status
        new_priority = priority if priority is not None else task.priority
        new_due = due_at if due_at is not None else task.due_at
        now = _utc_now()
        self._db.execute(
            """
            UPDATE tasks
            SET title = ?, description = ?, status = ?, priority = ?, due_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_title, new_desc, new_status, new_priority, new_due, now, task_id),
        )
        self._db.commit()
        return self.get(task_id)

    def delete(self, task_id: int) -> None:
        self.get(task_id)
        self._db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self._db.commit()

    def list(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[Task]:
        if status:
            rows = self._db.fetchall(
                "SELECT * FROM tasks WHERE status = ? ORDER BY priority DESC, id DESC LIMIT ?",
                (status, limit),
            )
        else:
            rows = self._db.fetchall(
                "SELECT * FROM tasks ORDER BY priority DESC, id DESC LIMIT ?",
                (limit,),
            )
        return [Task.from_row(r) for r in rows]
