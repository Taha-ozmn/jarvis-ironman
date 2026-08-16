"""Local notes + calendar tools (N-11) — SQLite-backed, no external MCP required."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _insert_id(db: Any, sql: str, params: Sequence[Any]) -> int:
    """Insert and return id — SQLite lastrowid or Postgres RETURNING."""
    from storage.backend import backend_kind

    if backend_kind(db) == "postgres":
        if "returning" not in sql.lower():
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
        row = db.fetchone(sql, params)
        db.commit()
        if row is None:
            raise RuntimeError("insert returned no id")
        return int(row["id"])
    cur = db.execute(sql, params)
    db.commit()
    return int(cur.lastrowid)


def _parse_when(raw: str) -> str:
    """Accept ISO-ish or relative 'today' / 'tomorrow' (+ optional HH:MM)."""
    text = (raw or "").strip().lower()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    if not text or text in ("now", "şimdi", "simdi"):
        return now.isoformat()
    if text.startswith("today") or text.startswith("bugün") or text.startswith("bugun"):
        base = now.replace(hour=9, minute=0)
        parts = text.split()
        if len(parts) >= 2 and ":" in parts[-1]:
            try:
                hh, mm = parts[-1].split(":", 1)
                base = base.replace(hour=int(hh), minute=int(mm))
            except ValueError:
                pass
        return base.isoformat()
    if text.startswith("tomorrow") or text.startswith("yarın") or text.startswith("yarin"):
        base = (now + timedelta(days=1)).replace(hour=9, minute=0)
        parts = text.split()
        if len(parts) >= 2 and ":" in parts[-1]:
            try:
                hh, mm = parts[-1].split(":", 1)
                base = base.replace(hour=int(hh), minute=int(mm))
            except ValueError:
                pass
        return base.isoformat()
    # Assume caller passed ISO / sortable datetime
    return raw.strip()


class CalendarNotesStore:
    """Thin CRUD over notes + calendar_events tables."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def create_note(self, body: str, *, title: str = "", tags: str = "") -> int:
        ts = _now_iso()
        return _insert_id(
            self._db,
            """
            INSERT INTO notes (title, body, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (title.strip(), body.strip(), tags.strip(), ts, ts),
        )

    def list_notes(self, *, limit: int = 10) -> list[dict[str, Any]]:
        rows = self._db.fetchall(
            """
            SELECT id, title, body, tags, created_at, updated_at
            FROM notes ORDER BY updated_at DESC LIMIT ?
            """,
            (max(1, min(50, limit)),),
        )
        return [dict(r) for r in rows]

    def search_notes(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        q = f"%{(query or '').strip()}%"
        rows = self._db.fetchall(
            """
            SELECT id, title, body, tags, created_at, updated_at
            FROM notes
            WHERE body LIKE ? OR title LIKE ? OR tags LIKE ?
            ORDER BY updated_at DESC LIMIT ?
            """,
            (q, q, q, max(1, min(50, limit))),
        )
        return [dict(r) for r in rows]

    def create_event(
        self,
        title: str,
        starts_at: str,
        *,
        ends_at: str = "",
        location: str = "",
        notes: str = "",
    ) -> int:
        ts = _now_iso()
        return _insert_id(
            self._db,
            """
            INSERT INTO calendar_events
                (title, starts_at, ends_at, location, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                title.strip(),
                _parse_when(starts_at),
                ends_at.strip() or None,
                location.strip(),
                notes.strip(),
                ts,
            ),
        )

    def list_events(
        self,
        *,
        from_iso: Optional[str] = None,
        to_iso: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        start = from_iso or _now_iso()[:10]  # today UTC date prefix
        end = to_iso or (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        rows = self._db.fetchall(
            """
            SELECT id, title, starts_at, ends_at, location, notes, created_at
            FROM calendar_events
            WHERE starts_at >= ? AND starts_at <= ?
            ORDER BY starts_at ASC LIMIT ?
            """,
            (start, end, max(1, min(50, limit))),
        )
        return [dict(r) for r in rows]

    def today_events(self, *, limit: int = 20) -> list[dict[str, Any]]:
        day = datetime.now(timezone.utc).date().isoformat()
        next_day = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
        return self.list_events(from_iso=day, to_iso=next_day, limit=limit)


def _fmt_notes(items: list[dict[str, Any]]) -> str:
    if not items:
        return "No notes."
    parts = []
    for n in items:
        title = (n.get("title") or "").strip()
        body = (n.get("body") or "").strip()
        label = f"#{n['id']} {title}: {body}" if title else f"#{n['id']} {body}"
        parts.append(label[:80])
    text = "; ".join(parts)
    return text if len(text) <= 240 else text[:237] + "…"


def _fmt_events(items: list[dict[str, Any]]) -> str:
    if not items:
        return "No events."
    parts = []
    for e in items:
        when = str(e.get("starts_at") or "")[:16]
        parts.append(f"#{e['id']} {when} {e.get('title')}")
    text = "; ".join(parts)
    return text if len(text) <= 240 else text[:237] + "…"


class NotesCreateTool(BaseTool):
    name = "notes.create"
    description = "Save a local note"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"body": {"type": "str", "required": True}}

    def __init__(self, store: CalendarNotesStore) -> None:
        self._store = store

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        body = str(arguments.get("body") or "").strip()
        if not body:
            return ToolResult(ok=False, error="Note body required")
        title = str(arguments.get("title") or "")
        tags = str(arguments.get("tags") or "")
        note_id = self._store.create_note(body, title=title, tags=tags)
        return ToolResult(ok=True, data=f"Note #{note_id} saved.")


class NotesListTool(BaseTool):
    name = "notes.list"
    description = "List recent local notes"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def __init__(self, store: CalendarNotesStore) -> None:
        self._store = store

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        limit = int(arguments.get("limit") or 10)
        return ToolResult(ok=True, data=_fmt_notes(self._store.list_notes(limit=limit)))


class NotesSearchTool(BaseTool):
    name = "notes.search"
    description = "Search local notes"
    permission_level = PermissionLevel.READ
    input_schema = {"query": {"type": "str", "required": True}}

    def __init__(self, store: CalendarNotesStore) -> None:
        self._store = store

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, error="query required")
        limit = int(arguments.get("limit") or 10)
        return ToolResult(
            ok=True,
            data=_fmt_notes(self._store.search_notes(query, limit=limit)),
        )


class CalendarCreateEventTool(BaseTool):
    name = "calendar.create_event"
    description = "Create a local calendar event"
    permission_level = PermissionLevel.LOCAL
    input_schema = {
        "title": {"type": "str", "required": True},
        "starts_at": {"type": "str", "required": True},
    }

    def __init__(self, store: CalendarNotesStore) -> None:
        self._store = store

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        title = str(arguments.get("title") or "").strip()
        starts = str(arguments.get("starts_at") or "").strip()
        if not title or not starts:
            return ToolResult(ok=False, error="title and starts_at required")
        eid = self._store.create_event(
            title,
            starts,
            ends_at=str(arguments.get("ends_at") or ""),
            location=str(arguments.get("location") or ""),
            notes=str(arguments.get("notes") or ""),
        )
        return ToolResult(ok=True, data=f"Event #{eid} created: {title}.")


class CalendarListTool(BaseTool):
    name = "calendar.list"
    description = "List upcoming local calendar events"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def __init__(self, store: CalendarNotesStore) -> None:
        self._store = store

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        limit = int(arguments.get("limit") or 20)
        items = self._store.list_events(limit=limit)
        return ToolResult(ok=True, data=_fmt_events(items))


class CalendarTodayTool(BaseTool):
    name = "calendar.today"
    description = "List today's local calendar events"
    permission_level = PermissionLevel.READ
    input_schema: dict = {}

    def __init__(self, store: CalendarNotesStore) -> None:
        self._store = store

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        items = self._store.today_events(limit=int(arguments.get("limit") or 20))
        return ToolResult(ok=True, data=_fmt_events(items))


def register_calendar_notes_tools(registry: Any, db: Any) -> CalendarNotesStore:
    store = CalendarNotesStore(db)
    for tool in (
        NotesCreateTool(store),
        NotesListTool(store),
        NotesSearchTool(store),
        CalendarCreateEventTool(store),
        CalendarListTool(store),
        CalendarTodayTool(store),
    ):
        registry.register(tool)
    return store
