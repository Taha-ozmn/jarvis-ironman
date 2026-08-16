# JARVIS 2.0 — Automation packs

Place YAML files in `config/automation_packs/`. On `JarvisOS.start_background()`,
`automation.packs.load_automation_packs` creates missing rules **by name** (idempotent).

```yaml
name: Pack — morning status
enabled: false          # opt-in; set true to activate
trigger:
  type: daily           # daily | weekly | interval | file_watch | manual
  hour: 9
  minute: 0
action:
  type: briefing        # briefing | remind_tasks | speak | tool
  force: false
```

Requires PyYAML (`yaml` in requirements). Missing packs dir is OK.
