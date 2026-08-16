# JARVIS 2.0 — Architecture (concise)

```
Mic / HUD
   → JarvisCore.process_command
      → JarvisOS.handle_turn
         → Fast tools (CommandRouter + ExecutionEngine)
         → meta / legacy
         → complexity + degraded gate
         → Cursor DeepBrain (MEDIUM+)
```

| Concern | Module |
|---------|--------|
| Turn entry | `core/app.py` `handle_turn` |
| Complexity | `core/complexity.py` |
| Execute + retry + evidence | `core/execution_engine.py` |
| Cancel | `core/cancellation.py` |
| Memory rank | `memory/retrieval.py` |
| Degraded | `core/degraded.py` |
| Model pick | `brain/model_router.py` |

**KEEP:** voice, HUD, Cursor, ToolRegistry, SQLite, permissions/audit.  
**Avoid:** full rewrite, forced PostgreSQL, removing voice/HUD/Cursor.
