"""Live telemetry for Iron Man HUD."""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
from typing import Any


def get_telemetry(model: str = "composer-2.5") -> dict[str, Any]:
    now = datetime.datetime.now()
    hour = now.hour
    if hour < 12:
        period = "MORNING"
    elif hour < 18:
        period = "AFTERNOON"
    else:
        period = "EVENING"

    cpu = _cpu_load()
    mem = _memory_used()
    disk = shutil.disk_usage("/")
    disk_pct = int(disk.used / disk.total * 100) if disk.total else 0

    return {
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%d %b %Y").upper(),
        "period": period,
        "cpu": f"{cpu}%",
        "memory": f"{mem}%",
        "disk": f"{disk_pct}%",
        "model": model,
        "neural": "ONLINE",
        "voice": "RYAN NEURAL",
        "macos": "CONNECTED",
        "cursor": "BRIDGE OK",
        "systems": "NOMINAL",
    }


def _cpu_load() -> int:
    try:
        load = os.getloadavg()[0]
        cores = os.cpu_count() or 1
        return min(99, int(load / cores * 100))
    except (AttributeError, OSError):
        return 0


def _memory_used() -> int:
    try:
        result = subprocess.run(
            ["vm_stat"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        pages = {}
        for line in result.stdout.splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                pages[key.strip()] = int(val.strip().rstrip("."))
        page_size = 4096
        try:
            page_size = int(
                subprocess.run(
                    ["sysctl", "-n", "hw.pagesize"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                ).stdout.strip()
            )
        except (ValueError, subprocess.SubprocessError):
            pass
        active = pages.get("Pages active", 0) + pages.get("Pages wired down", 0)
        inactive = pages.get("Pages inactive", 0) + pages.get("Pages speculative", 0)
        total = active + inactive + pages.get("Pages free", 0)
        if total <= 0:
            return 0
        return min(99, int(active / total * 100))
    except (subprocess.SubprocessError, ValueError, KeyError):
        return 0
