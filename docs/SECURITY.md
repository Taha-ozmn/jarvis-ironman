# JARVIS 2.0 — Security Preset

## Safe autonomy (default here)

```yaml
jarvis2:
  max_permission_level: 3
  autonomy_level: 4               # 1=ask all … 4=confirm DANGEROUS only
  auto_approve_dangerous: false   # DANGEROUS confirms unless autonomy≥4 + this true
  max_agent_steps: 12
  confirm_timeout: 60
system:
  full_shell_access: false        # default deny free-form shell
```

| Autonomy | Auto-run | Confirm at |
|----------|----------|------------|
| 1 | nothing | READ+ |
| 2 | READ | LOCAL+ |
| 3 | READ–LOCAL | SYSTEM+ |
| 4 (default) | READ–SYSTEM | DANGEROUS |

| Permission | Examples | Gate |
|------------|----------|------|
| 0 READ | time, memory search | always if max allows |
| 1 LOCAL | memory save, tasks | max_level ≥ 1 |
| 2 SYSTEM | open app, shell (safe) | max_level ≥ 2 |
| 3 DANGEROUS | destructive shell, git push | confirm (unless auto_approve + autonomy 4) |

## Full autonomy (not default)

Only for a locked-down personal machine you fully control:

```yaml
jarvis2:
  autonomy_level: 4
  auto_approve_dangerous: true
```

Audit log (`security.audit.AuditLog`) still records every tool call with `request_id` when set.

## Rules

- Never claim success without evidence / verify where configured.
- Do not disable audit.
- Prefer pausing plans on Level-3 denial (`waiting`) over silent skip.
- Prefer `dry run` / `ne yapacağını göster` before risky multi-step plans.
