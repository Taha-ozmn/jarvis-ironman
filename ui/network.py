"""LAN address helpers for HUD phone links."""

from __future__ import annotations

import socket
import subprocess
from typing import Optional


def collect_ipv4_addresses() -> list[str]:
    """Non-loopback IPv4 addresses (Wi‑Fi, USB tether, Personal Hotspot, etc.)."""
    ips: list[str] = []
    try:
        out = subprocess.check_output(["ifconfig"], text=True, timeout=3)
        for line in out.splitlines():
            stripped = line.strip()
            if not stripped.startswith("inet ") or "127.0.0.1" in stripped:
                continue
            parts = stripped.split()
            if len(parts) >= 2 and not parts[1].startswith("127."):
                ips.append(parts[1])
    except (OSError, subprocess.SubprocessError, FileNotFoundError):
        pass
    seen: set[str] = set()
    unique: list[str] = []
    for ip in ips:
        if ip not in seen:
            seen.add(ip)
            unique.append(ip)
    return unique


def primary_lan_ip() -> Optional[str]:
    """Best-effort primary LAN IPv4 for phone / tablet HUD links."""
    ips = collect_ipv4_addresses()
    for ip in ips:
        if ip.startswith("172.20.10."):
            return ip
    routable = [ip for ip in ips if not ip.startswith("169.254.")]
    if routable:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                route_ip = sock.getsockname()[0]
            if route_ip in routable:
                return route_ip
        except OSError:
            pass
        return routable[0]
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return None
