"""Optional stdio MCP server for calendar/notes (N-11 pack).

Configure in config.yaml when desired:

  jarvis2:
    mcp:
      servers:
        - name: calendar_notes
          transport: stdio
          command: python3
          args: ["-m", "integrations.local_calendar_notes_mcp"]
          permission_level: 1

Uses a dedicated SQLite file under data/mcp_calendar_notes.db so the
subprocess does not share the main OS connection.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory.database import Database
from tools.calendar_notes import CalendarNotesStore


def _read_message() -> dict | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.readline()
        if not line:
            return None
        if line in ("\r\n", "\n"):
            break
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    length = int(headers.get("content-length") or "0")
    body = sys.stdin.read(length)
    if not body:
        return None
    return json.loads(body)


def _write_message(msg: dict) -> None:
    body = json.dumps(msg, ensure_ascii=False)
    data = body.encode("utf-8")
    sys.stdout.write(f"Content-Length: {len(data)}\r\n\r\n")
    sys.stdout.write(body)
    sys.stdout.flush()


TOOLS = [
    {
        "name": "notes_create",
        "description": "Save a note",
        "inputSchema": {
            "type": "object",
            "properties": {
                "body": {"type": "string"},
                "title": {"type": "string"},
            },
            "required": ["body"],
        },
    },
    {
        "name": "notes_list",
        "description": "List recent notes",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "number"}}},
    },
    {
        "name": "calendar_today",
        "description": "List today's events",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "calendar_create_event",
        "description": "Create a calendar event",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "starts_at": {"type": "string"},
            },
            "required": ["title", "starts_at"],
        },
    },
]


def _handle_call(store: CalendarNotesStore, name: str, args: dict) -> str:
    if name == "notes_create":
        nid = store.create_note(
            str(args.get("body") or ""),
            title=str(args.get("title") or ""),
        )
        return f"Note #{nid} saved."
    if name == "notes_list":
        items = store.list_notes(limit=int(args.get("limit") or 10))
        if not items:
            return "No notes."
        return "; ".join(f"#{n['id']} {n.get('body','')[:60]}" for n in items)
    if name == "calendar_today":
        items = store.today_events()
        if not items:
            return "No events today."
        return "; ".join(f"#{e['id']} {e.get('title')}" for e in items)
    if name == "calendar_create_event":
        eid = store.create_event(
            str(args.get("title") or ""),
            str(args.get("starts_at") or "today"),
        )
        return f"Event #{eid} created."
    return f"Unknown tool: {name}"


def main() -> None:
    db_path = ROOT / "data" / "mcp_calendar_notes.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)
    db.migrate()
    store = CalendarNotesStore(db)

    while True:
        msg = _read_message()
        if msg is None:
            break
        method = msg.get("method")
        req_id = msg.get("id")
        if method == "notifications/initialized":
            continue
        if method == "initialize":
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "calendar-notes", "version": "0.1"},
                    },
                }
            )
            continue
        if method == "tools/list":
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": TOOLS},
                }
            )
            continue
        if method == "tools/call":
            params = msg.get("params") or {}
            name = str(params.get("name") or "")
            args = params.get("arguments") or {}
            try:
                text = _handle_call(store, name, args)
                err = False
            except Exception as exc:  # noqa: BLE001 — surface to MCP client
                text = str(exc)
                err = True
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": text}],
                        "isError": err,
                    },
                }
            )
            continue
        if req_id is not None:
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            )


if __name__ == "__main__":
    main()
