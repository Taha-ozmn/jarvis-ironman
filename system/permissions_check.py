"""Detectable macOS privacy / TCC permission probes (honest, never silent-grant)."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

# Monterey / Ventura-era TCC panes (best-effort; Apple may change URLs).
PRIVACY_PANE_URLS = {
    "screen_recording": (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
    ),
    "accessibility": (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
    ),
    "full_disk_access": (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
    ),
    "automation": (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"
    ),
    "microphone": (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
    ),
}


def open_privacy_settings(pane: str = "screen_recording") -> tuple[bool, str]:
    """Open System Settings to a Privacy pane. Cannot grant TCC from code."""
    url = PRIVACY_PANE_URLS.get(pane) or PRIVACY_PANE_URLS["screen_recording"]
    try:
        result = subprocess.run(
            ["open", url],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception as err:
        return False, str(err)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "open failed").strip()[:160]
    return True, url


def open_all_privacy_settings() -> list[tuple[str, bool, str]]:
    """Open every privacy pane JARVIS needs (user still toggles each switch)."""
    results: list[tuple[str, bool, str]] = []
    for pane in (
        "accessibility",
        "screen_recording",
        "full_disk_access",
        "automation",
        "microphone",
    ):
        ok, detail = open_privacy_settings(pane)
        results.append((pane, ok, detail))
    return results


def probe_macos_permissions() -> dict[str, Any]:
    """Best-effort probes. User must grant TCC in System Settings — code cannot."""
    checks: list[dict[str, Any]] = []

    # Accessibility (AXIsProcessTrusted)
    ax_ok = False
    ax_detail = "unknown"
    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get name of first process',
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        ax_ok = result.returncode == 0
        ax_detail = (
            "System Events reachable"
            if ax_ok
            else ((result.stderr or result.stdout or "denied").strip()[:120])
        )
    except Exception as err:
        ax_detail = str(err)
    checks.append(
        {
            "id": "accessibility_automation",
            "label": "Accessibility / System Events",
            "ok": ax_ok,
            "detail": ax_detail,
            "settings": "Privacy & Security → Accessibility (+ Automation)",
        }
    )

    # Screen Recording — try screencapture
    screen_ok = False
    screen_detail = "unknown"
    try:
        path = Path(tempfile.gettempdir()) / "jarvis-perm-screen.png"
        result = subprocess.run(
            ["screencapture", "-x", "-t", "png", str(path)],
            capture_output=True,
            text=True,
            timeout=12,
        )
        screen_ok = result.returncode == 0 and path.exists() and path.stat().st_size > 0
        screen_detail = (
            f"captured {path.stat().st_size} bytes"
            if screen_ok
            else ((result.stderr or "capture failed/denied").strip()[:120])
        )
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
    except Exception as err:
        screen_detail = str(err)
    checks.append(
        {
            "id": "screen_recording",
            "label": "Screen Recording",
            "ok": screen_ok,
            "detail": screen_detail,
            "settings": "Privacy & Security → Screen Recording",
        }
    )

    # Full Disk Access — probe Mail library (common FDA target)
    fda_ok = False
    fda_detail = "unknown"
    mail_dir = Path.home() / "Library" / "Mail"
    try:
        if mail_dir.exists():
            # listing may fail without FDA on newer macOS
            _ = list(mail_dir.iterdir())
            fda_ok = True
            fda_detail = "Library/Mail readable"
        else:
            fda_ok = True
            fda_detail = "Library/Mail missing (ok)"
    except PermissionError:
        fda_ok = False
        fda_detail = "Library/Mail not readable — grant Full Disk Access"
    except Exception as err:
        fda_detail = str(err)[:120]
    checks.append(
        {
            "id": "full_disk_access",
            "label": "Full Disk Access (probe)",
            "ok": fda_ok,
            "detail": fda_detail,
            "settings": "Privacy & Security → Full Disk Access",
        }
    )

    # Automation — Mail.app
    mail_ok = False
    mail_detail = "unknown"
    try:
        result = subprocess.run(
            ["osascript", "-e", 'tell application "Mail" to get name'],
            capture_output=True,
            text=True,
            timeout=10,
        )
        mail_ok = result.returncode == 0
        mail_detail = (
            (result.stdout or "").strip() or "Mail reachable"
            if mail_ok
            else ((result.stderr or "Mail automation denied").strip()[:120])
        )
    except Exception as err:
        mail_detail = str(err)
    checks.append(
        {
            "id": "automation_mail",
            "label": "Automation → Mail",
            "ok": mail_ok,
            "detail": mail_detail,
            "settings": "Privacy & Security → Automation → Mail",
        }
    )

    # Microphone — cannot reliably probe without requesting; report manual
    checks.append(
        {
            "id": "microphone",
            "label": "Microphone",
            "ok": None,
            "detail": "Cannot auto-detect; grant if voice listen fails",
            "settings": "Privacy & Security → Microphone",
        }
    )

    passed = sum(1 for c in checks if c.get("ok") is True)
    known = sum(1 for c in checks if c.get("ok") is not None)
    return {
        "ok": known > 0 and all(c["ok"] for c in checks if c.get("ok") is not None),
        "passed": passed,
        "total_probeable": known,
        "checks": checks,
        "note": (
            "macOS TCC toggles can ONLY be enabled by you in System Settings. "
            "JARVIS cannot grant Screen Recording / Accessibility / FDA silently."
        ),
    }


def format_permissions_speech(report: dict[str, Any]) -> str:
    checks = report.get("checks") or []
    bits: list[str] = []
    screen_missing = False
    for c in checks:
        label = c.get("label") or c.get("id")
        ok = c.get("ok")
        if c.get("id") == "screen_recording" and ok is False:
            screen_missing = True
        if ok is True:
            bits.append(f"{label}: OK")
        elif ok is False:
            bits.append(f"{label}: MISSING")
        else:
            bits.append(f"{label}: check manually")
    head = (
        f"{report.get('passed', 0)}/{report.get('total_probeable', 0)} "
        "detectable permissions OK."
    )
    body = "; ".join(bits)
    note = (
        " Code cannot silently grant TCC permissions you haven't approved "
        "in System Settings."
    )
    if screen_missing:
        note += (
            " For Screen Recording: System Settings → Privacy & Security → "
            "Screen Recording. Enable the app running JARVIS "
            "(Terminal, Cursor, or Python), then quit and restart JARVIS."
        )
    msg = f"{head} {body}.{note}"
    if len(msg) > 520:
        msg = msg[:517] + "…"
    return msg
