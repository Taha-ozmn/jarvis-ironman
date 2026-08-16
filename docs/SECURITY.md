# JARVIS 2.0 — Security Preset

## Safe autonomy (default here)

```yaml
jarvis2:
  max_permission_level: 3
  auto_approve_dangerous: false   # Level-3 always confirms
  confirm_timeout: 60
system:
  full_shell_access: true         # shell tool exists; still gated by level
```

| Level | Examples | Gate |
|-------|----------|------|
| 0 READ | time, memory search | always |
| 1 WRITE | memory save, tasks | max_level ≥ 1 |
| 2 SYSTEM | open app, shell (safe) | max_level ≥ 2 |
| 3 DANGEROUS | destructive shell, git push | confirm required |

## Full autonomy (not default)

Only for a locked-down personal machine you fully control:

```yaml
jarvis2:
  auto_approve_dangerous: true
```

Audit log (`security.audit.AuditLog`) still records every tool call with `request_id` when set.

## Rules

- Never claim success without evidence / verify where configured.
- Do not disable audit.
- Prefer pausing plans on Level-3 denial (`waiting`) over silent skip.
