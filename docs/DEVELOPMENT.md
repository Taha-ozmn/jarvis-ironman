# JARVIS 2.0 — Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # if present — never commit secrets
./start.sh --browser   # or python3 main.py
python3 -m unittest discover -s tests -v
```

## Layout

| Path | Role |
|------|------|
| `main.py` | Voice/HUD host (`JarvisCore`) |
| `core/` | OS facade, decision, execution, recovery |
| `tools/` | Tool implementations + bootstrap |
| `memory/` | SQLite + retrieval |
| `brain/` | Cursor DeepBrain + model router |
| `ui/` | Iron Man HUD |
| `automation/` | Scheduler + packs |

## Rules

- Prefer incremental PRs on `cursor/*-b2cd`
- Don't claim tool success without verify/evidence
- Keep `auto_approve_dangerous: false` unless intentional
