# JARVIS 2.0 — Model Routing

## Config

```yaml
jarvis:
  model: gemini-3-flash
  models:
    chat: gemini-3-flash      # cheap
    action: gemini-3-flash
    search: gemini-3-flash
    code: composer-2.5       # smart
    complex: composer-2.5
    deep: auto
    default: gemini-3-flash
  model_routing: true
```

## Selection

| Complexity | Route |
|------------|--------|
| CHAT / SIMPLE | cheap (`chat`) — Cursor usually gated off |
| MEDIUM | `search` / default |
| COMPLEX / AUTONOMOUS | `complex` / `deep` |
| Degraded mode | always cheap `chat`; Cursor blocked |

Helpers: `ModelRouter.pick_for_complexity`, `core.model_routing.route_model`.
