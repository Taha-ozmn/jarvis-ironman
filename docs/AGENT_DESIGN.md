# JARVIS 2.0 — Agent Design

## Loop (implemented)

```
User → JarvisOS.handle_turn
  → CommandRouter (tools)
  → meta / legacy
  → DecisionEngine (CHAT/SIMPLE/degraded gate)
  → Cursor DeepBrain (MEDIUM+)
```

Plans:

```
Planner.create → ExecutionEngine.execute_plan
  → per-step permission / confirm / validate / run / verify / evidence
  → cancel token · pause on L3 · resume
```

## Controls

| Knob | Where |
|------|-------|
| Complexity | `core/complexity.py` |
| Cursor policy | `core/decision.py` |
| Retries | `jarvis2.tool_max_retries` (≤3) |
| Plan budget | `jarvis2.max_agent_steps` |
| Autonomy | `jarvis2.autonomy_level` (1–4) |
| Dry-run | plan dry-run path |

## Golden

Evidence before claims · No infinite loops · User can cancel · Dangerous ops confirm (unless autonomy allows).
