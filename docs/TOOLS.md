# JARVIS 2.0 — Tools & Plugins

## Contract

Every tool subclasses `tools.base.BaseTool`:

| Hook | Required | Behavior |
|------|----------|----------|
| `run(args)` | yes | Return `ToolResult` — never raise into the voice loop |
| `validate(args)` | no | Return error string or `None` |
| `rollback(args, previous)` | no | Best-effort undo; default honest failure |
| `verify(result)` | no | Optional post-check (engine may also call `core.verification`) |

`ToolResult.evidence` holds a dict (see `core.evidence.ExecutionEvidence`).

## Registry

`tools.bootstrap.register_phase3_tools` registers built-ins.  
Plugins: `tools.packages.register_plugin(name, fn)` then `load_plugins(registry, ctx)` — failures are isolated.

## Permissions

Levels 0–3 via `PermissionGate`. Level 3 (`DANGEROUS`) requires `ConfirmationGate` unless `jarvis2.auto_approve_dangerous: true` (default **false** in this repo).
