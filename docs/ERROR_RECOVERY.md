# JARVIS 2.0 — Error Recovery

## Classify → retry → speak

`core.recovery`:

1. `classify_error` — transient vs permanent
2. `is_retryable` — permanent denials (permission, confirmation, stub, required) never retry
3. `sleep_backoff` — exponential backoff between attempts
4. `user_safe_speech` / `voice.speech_clean.speak_safe` — no raw `Could not open …` to TTS

## Bounds

- Single-tool path: `jarvis2.tool_max_retries` (capped at 3)
- Plan path: `jarvis2.plan_max_retries` per step
- Cancel: `CancellationToken` + voice stop (`dur` / `stop`) via `JarvisOS.cancel_active_plan`

## Degraded mode

`core.degraded.DegradedMode` — when active, `handle_turn` never allows Cursor; Fast tools keep working. Model router forces the cheap `chat` model.
