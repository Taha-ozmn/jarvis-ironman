# JARVIS 2.0 — Architecture (concise)

```
Mic / HUD / Desktop
   → JarvisCore.process_command
      → voice confirm (if pending)
      → JarvisOS.handle_turn
         → Fast tools (CommandRouter)
         → meta / quick / legacy
         → DecisionEngine gate (CHAT/SIMPLE/degraded)
         → Cursor DeepBrain (MEDIUM+)
```

| Concern | Module |
|---------|--------|
| Turn entry | `core/app.py` `handle_turn` |
| Cursor policy | `core/decision.py` `DecisionEngine` |
| Complexity | `core/complexity.py` |
| Execute + evidence | `core/execution_engine.py` |
| Cancel | `core/cancellation.py` |
| Memory | `memory/retrieval.py` |
| Degraded | `core/degraded.py` |
| HUD | `ui/server.py` + `ui/index.html` + `ui/desktop.py` |

**KEEP:** voice, HUD, Cursor, ToolRegistry, SQLite, permissions/audit.  
**Avoid:** full rewrite, forced PostgreSQL, removing voice/HUD/Cursor.
