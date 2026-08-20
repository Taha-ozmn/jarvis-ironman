# macOS Permissions Checklist (JARVIS)

JARVIS can **request** capabilities, but **cannot silently grant** macOS TCC privacy toggles.
You must enable these in **System Settings → Privacy & Security** for the app that runs JARVIS
(Terminal, Cursor, Python, or your packaged binary).

## Required for full autonomy

| Permission | Why JARVIS needs it | How to grant |
|---|---|---|
| **Accessibility** | UI automation, System Events, some app control | Privacy & Security → Accessibility → enable the host app |
| **Screen Recording** | `screen.capture` / `screen.describe` (`screencapture`) | Privacy & Security → Screen Recording → enable host app, then quit/reopen |
| **Full Disk Access** | Mail library / protected folders / broad file reads | Privacy & Security → Full Disk Access → enable host app |
| **Automation** | AppleScript control of **Mail**, **Calendar**, **System Events** | Privacy & Security → Automation → host app → Mail / Calendar / System Events |
| **Microphone** | Voice listen (STT) | Privacy & Security → Microphone → enable host app |
| **Notifications** (optional) | `system.notify` banners | System Settings → Notifications → host app |

## Config (software side)

In `config.yaml`:

- `jarvis.ai_only: false` — local Mac tools always preferred for actions
- `jarvis.full_access: true` / `sandbox: false` — Cursor agent Mac access
- `jarvis2.max_permission_level: 3` — allow Level-3 tools
- `jarvis2.auto_approve_level_0_1_2: true` — no confirm for reversible/important notify (L0–L2)
- `jarvis2.full_autonomy: true` — auto-approve Level 3 **with audit log**
- Catastrophic patterns (`rm -rf /`, disk erase, fork bomb) stay **hard-blocked** even with full autonomy

## Verify

Say / type:

- `izinleri kontrol et` → runs `system.check_permissions` (opens Screen Recording pane if missing)
- `ekranda ne var` → screen describe (needs Screen Recording)
- `maillerim` / `gelen kutusu` → Mail inbox (needs Automation → Mail)
- `bugünkü toplantılar` / `takvim` → Calendar events (needs Automation → Calendar)

## Screen Recording (Terminal / Python)

JARVIS cannot flip the TCC switch. Grant it like this:

1. System Settings → Privacy & Security → **Screen Recording**
2. **Best practice:** enable **Terminal.app** and/or **Cursor** (the app that launches JARVIS) — often enough; Finder search for `python` usually finds nothing useful
3. To add Python explicitly: click **+** → press **Cmd+Shift+G** (Go to Folder) → paste one of:
   - `/Users/mac/Desktop/jarvis-ironman-main/.venv/bin/python` (JARVIS venv; resolves to Homebrew Python)
   - `/usr/local/opt/python@3.14/bin/python3.14` (real binary on this Mac)
   - `/usr/local/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/Versions/3.14/bin/python3.14`
4. Quit the host app completely, reopen it, start JARVIS again

Deep link (JARVIS also tries this when the probe fails):

```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
```

## Playwright / Chromium (optional click & fill)

JARVIS core, voice, HUD, and `browser.open_url` do **not** need Playwright.
Interactive `browser.click` / `browser.fill_form` need the optional package + Chromium.

```bash
.venv/bin/pip install -r requirements-optional.txt
.venv/bin/playwright install chromium
```

### macOS 12 (Monterey)

- Playwright **1.62+** fails with: `Playwright does not support chromium on mac12`.
- `requirements-optional.txt` pins `playwright>=1.40.0,<1.62.0` (verified: **1.61.0** installs and launches Chromium on 12.7.x).
- If you stay on Monterey: use that pin; do not upgrade to 1.62+.
- If Chromium is missing or blocked: JARVIS still boots; use `browser.open_url` / `get_page_text`. Click/fill stay unavailable with a Turkish error.
- Alternative: upgrade to **macOS 13+** and you may use newer Playwright.

### macOS 13+

Upper bound `<1.62` can be relaxed if you want the latest Playwright.

## Honest limits

- Toggling TCC from code is **not allowed** by Apple on modern macOS.
- First use of Mail AppleScript or System Events may show a system consent dialog — click **OK**.
- If a probe reports EKSİK, open System Settings and grant the permission, then restart JARVIS.
