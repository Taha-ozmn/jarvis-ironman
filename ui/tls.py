"""Self-signed TLS for iPhone microphone access (secure context on LAN)."""

from __future__ import annotations

import json
import ssl
import subprocess
from pathlib import Path
from typing import Optional

CERT_DIR = Path(__file__).resolve().parent.parent / "data" / "hud_tls"
CERT_FILE = CERT_DIR / "jarvis-hud.crt"
KEY_FILE = CERT_DIR / "jarvis-hud.key"
META_FILE = CERT_DIR / "san.json"


def _collect_ips() -> list[str]:
    from ui.network import collect_ipv4_addresses

    ips = ["127.0.0.1"]
    ips.extend(collect_ipv4_addresses())
    unique: list[str] = []
    seen: set[str] = set()
    for ip in ips:
        if ip not in seen:
            seen.add(ip)
            unique.append(ip)
    return unique


def _stored_ips() -> set[str]:
    if not META_FILE.is_file():
        return set()
    try:
        payload = json.loads(META_FILE.read_text(encoding="utf-8"))
        return set(payload.get("ips") or [])
    except (json.JSONDecodeError, OSError):
        return set()


def _write_openssl_config(path: Path, ips: list[str]) -> None:
    lines = [
        "[req]",
        "distinguished_name = req_distinguished_name",
        "x509_extensions = v3_req",
        "prompt = no",
        "",
        "[req_distinguished_name]",
        "CN = JARVIS HUD",
        "",
        "[v3_req]",
        "subjectAltName = @alt_names",
        "",
        "[alt_names]",
        "DNS.1 = localhost",
    ]
    idx = 1
    for ip in ips:
        try:
            ipaddress = __import__("ipaddress")
            parsed = ipaddress.ip_address(ip)
            if parsed.version == 4:
                lines.append(f"IP.{idx} = {ip}")
                idx += 1
        except ValueError:
            continue
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_hud_tls_cert(*, force: bool = False) -> tuple[Path, Path]:
    """Return (cert, key) paths, generating or refreshing SANs when LAN IPs change."""
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    ips = _collect_ips()
    needed = set(ips)
    if (
        not force
        and CERT_FILE.is_file()
        and KEY_FILE.is_file()
        and needed <= _stored_ips()
    ):
        return CERT_FILE, KEY_FILE

    cfg = CERT_DIR / "openssl.cnf"
    _write_openssl_config(cfg, ips)
    cmd = [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-keyout",
        str(KEY_FILE),
        "-out",
        str(CERT_FILE),
        "-days",
        "825",
        "-nodes",
        "-config",
        str(cfg),
        "-extensions",
        "v3_req",
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    KEY_FILE.chmod(0o600)
    META_FILE.write_text(
        json.dumps({"ips": ips}, indent=2),
        encoding="utf-8",
    )
    return CERT_FILE, KEY_FILE


def hud_ssl_context(*, force_refresh: bool = False) -> ssl.SSLContext:
    cert, key = ensure_hud_tls_cert(force=force_refresh)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    return ctx


def tls_available() -> bool:
    try:
        subprocess.run(
            ["openssl", "version"],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        return False
