"""Cheap host CPU / RAM / swap snapshots for voice status + light mode."""

from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Any

_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}
_CACHE_TTL = 8.0

# Light-mode thresholds (percent / pages)
CPU_CRITICAL = 85
MEM_CRITICAL = 90
SWAP_USED_CRITICAL_MB = 256


def get_host_metrics(*, force: bool = False) -> dict[str, Any]:
    """Return cpu_pct, mem_pct, swap_used_mb, swap_active, light_mode."""
    now = time.monotonic()
    cached = _CACHE.get("payload")
    if (
        not force
        and cached is not None
        and now - float(_CACHE["ts"]) < _CACHE_TTL
    ):
        return dict(cached)

    cpu = _cpu_pct()
    mem = _memory_used_pct()
    swap_mb = _swap_used_mb()
    swap_active = swap_mb >= 1
    light = (
        cpu >= CPU_CRITICAL
        or mem >= MEM_CRITICAL
        or swap_mb >= SWAP_USED_CRITICAL_MB
    )
    payload = {
        "cpu_pct": cpu,
        "mem_pct": mem,
        "swap_used_mb": swap_mb,
        "swap_active": swap_active,
        "light_mode": light,
        "ts": time.time(),
    }
    _CACHE.update(ts=now, payload=payload)
    return dict(payload)


def format_host_status_en(metrics: dict[str, Any] | None = None) -> str:
    """Short factual English line for TTS."""
    m = metrics or get_host_metrics()
    cpu = int(m.get("cpu_pct") or 0)
    mem = int(m.get("mem_pct") or 0)
    swap_mb = int(m.get("swap_used_mb") or 0)
    swap_active = bool(m.get("swap_active"))
    light = bool(m.get("light_mode"))

    if light or mem >= 85 or cpu >= 80:
        verdict = "System under load"
    elif cpu >= 50 or mem >= 70:
        verdict = "System at moderate load"
    else:
        verdict = "System healthy"

    swap_part = (
        f"swap active ({swap_mb} MB)"
        if swap_active
        else "no swap"
    )
    line = f"{verdict}: CPU {cpu}%, RAM {mem}%, {swap_part}."
    if light:
        line += " Switching to light mode."
    return line


def format_host_status_tr(metrics: dict[str, Any] | None = None) -> str:
    """Legacy Turkish formatter — prefer format_host_status_en for spoken replies."""
    return format_host_status_en(metrics)


def format_host_status_en(metrics: dict[str, Any] | None = None) -> str:
    """Short factual English line for film JARVIS TTS."""
    m = metrics or get_host_metrics()
    cpu = int(m.get("cpu_pct") or 0)
    mem = int(m.get("mem_pct") or 0)
    swap_mb = int(m.get("swap_used_mb") or 0)
    swap_active = bool(m.get("swap_active"))
    light = bool(m.get("light_mode"))

    if light or mem >= 85 or cpu >= 80:
        verdict = "System under strain"
    elif cpu >= 50 or mem >= 70:
        verdict = "System under moderate load"
    else:
        verdict = "System healthy"

    swap_part = (
        f"swap active ({swap_mb} MB)"
        if swap_active
        else "no swap"
    )
    line = f"{verdict}: CPU {cpu}%, RAM {mem}%, {swap_part}."
    if light:
        line += " Switching to light mode."
    return line


def format_host_status(
    metrics: dict[str, Any] | None = None,
    *,
    language: str = "en",
) -> str:
    """Prefer English for spoken replies; TR kept for legacy callers."""
    if str(language or "").lower().startswith("tr"):
        return format_host_status_tr(metrics)
    return format_host_status_en(metrics)


def _cpu_pct() -> int:
    """Actual CPU busy % across all cores (not loadavg*100).

    ``ps -A -o %cpu`` sums per-core percentages; divide by core count so
    100% means all cores saturated. Falls back to normalized loadavg.
    """
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "%cpu="],
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout
        total = 0.0
        samples = 0
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                total += float(line)
                samples += 1
            except ValueError:
                continue
        if samples == 0:
            return _cpu_loadavg_pressure_pct()
        cores = max(1, os.cpu_count() or 1)
        return max(0, min(99, int(round(total / cores))))
    except (subprocess.SubprocessError, OSError, ValueError):
        return _cpu_loadavg_pressure_pct()


def _cpu_loadavg_pressure_pct() -> int:
    """Fallback pressure signal from 1-min loadavg / cores (0–99)."""
    try:
        load = os.getloadavg()[0]
        cores = max(1, os.cpu_count() or 1)
        return min(99, int(round(load / cores * 100)))
    except (AttributeError, OSError):
        return 0


def _memory_used_pct() -> int:
    try:
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

        memsize = 0
        try:
            memsize = int(
                subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                ).stdout.strip()
            )
        except (ValueError, subprocess.SubprocessError):
            pass

        result = subprocess.run(
            ["vm_stat"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        pages: dict[str, int] = {}
        for line in result.stdout.splitlines():
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            val = val.strip().rstrip(".")
            try:
                pages[key.strip()] = int(val)
            except ValueError:
                continue

        if memsize > 0 and page_size > 0:
            free = pages.get("Pages free", 0)
            used_pages = (memsize // page_size) - free
            total_pages = memsize // page_size
            if total_pages > 0:
                return min(99, int(used_pages / total_pages * 100))

        active = pages.get("Pages active", 0)
        wired = pages.get("Pages wired down", 0)
        compressed = pages.get("Pages occupied by compressor", 0)
        inactive = pages.get("Pages inactive", 0)
        speculative = pages.get("Pages speculative", 0)
        free = pages.get("Pages free", 0)
        used = active + wired + compressed
        total = used + inactive + speculative + free
        if total <= 0:
            return 0
        return min(99, int(used / total * 100))
    except (subprocess.SubprocessError, ValueError, KeyError, OSError):
        return 0


def _swap_used_mb() -> int:
    """Best-effort swap used in MB via `sysctl vm.swapusage`."""
    try:
        out = subprocess.run(
            ["sysctl", "-n", "vm.swapusage"],
            capture_output=True,
            text=True,
            timeout=1,
        ).stdout
        # e.g. "total = 2048.00M  used = 412.50M  free = 1635.50M  ..."
        m = re.search(r"used\s*=\s*([\d.]+)([MG])", out or "", re.I)
        if not m:
            return 0
        val = float(m.group(1))
        unit = m.group(2).upper()
        if unit == "G":
            val *= 1024
        return max(0, int(val))
    except (subprocess.SubprocessError, ValueError, OSError):
        return 0
