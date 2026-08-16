# JARVIS 2.0 — Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # if present — never commit secrets
./start.sh --browser   # or python3 main.py
python3 -m unittest discover -s tests -v
```

## Voice / mic (Phase 9)

| Path | Notes |
|------|-------|
| Browser HUD mic | Web Speech API — works without PyAudio |
| macOS native | `voice/macos_listen` helper when built |
| PyAudio fallback | Optional: `brew install portaudio && pip install PyAudio` |

PyAudio is **not** required for core OS / tool tests. If desktop mic fails, HUD browser mode still listens. Language: keep `voice.listen_language` primary tag aligned with `jarvis.language` when possible (`config/presets/safe.yaml`).

## Layout

| Path | Role |
|------|------|
| `main.py` | Voice/HUD host (`JarvisCore`) |
| `core/` | OS facade, decision, execution, recovery |
| `tools/` | Tool implementations + bootstrap |
| `memory/` | SQLite + retrieval |
| `storage/` | `StorageBackend` protocol (sqlite now) |
| `brain/` | Cursor DeepBrain + model router |
| `ui/` | Iron Man HUD |
| `automation/` | Scheduler + packs |
| `config/presets/` | Optional overlays (e.g. `safe.yaml`) |

## Rules

- Prefer incremental PRs on `cursor/*-b2cd`
- Don't claim tool success without verify/evidence
- Keep `auto_approve_dangerous: false` unless intentional
- Use `autonomy_level` + dry-run before risky multi-step work
