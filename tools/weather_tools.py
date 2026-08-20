"""Fast weather lookup via wttr.in — no LLM, no API key with connection recovery."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult
from core.connection_recovery import connection_recovery, ConnectionType

WTTR_UA = "curl/8.0 (JARVIS-weather)"
DEFAULT_TIMEOUT = 8.0


def fetch_weather(location: str = "", *, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Return a short spoken weather summary from wttr.in with connection recovery."""
    loc = (location or "").strip()
    if loc:
        path = urllib.parse.quote(loc.replace(" ", "+"))
        url = f"https://wttr.in/{path}?format=j1"
    else:
        url = "https://wttr.in/?format=j1"

    def _fetch_operation():
        req = urllib.request.Request(url, headers={"User-Agent": WTTR_UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))

        area = data.get("nearest_area") or [{}]
        area_name = ""
        if area:
            names = area[0].get("areaName") or [{}]
            area_name = str(names[0].get("value") or "").strip()

        current = (data.get("current_condition") or [{}])[0]
        temp_c = str(current.get("temp_C") or "").strip()
        desc_list = current.get("weatherDesc") or [{}]
        desc = str(desc_list[0].get("value") or "Unknown").strip()
        humidity = str(current.get("humidity") or "").strip()
        wind_kmph = str(current.get("windspeedKmph") or "").strip()

        place = area_name or loc or "your location"
        parts = [f"{place}: {desc}"]
        if temp_c:
            parts.append(f"{temp_c}°C")
        if humidity:
            parts.append(f"humidity {humidity}%")
        if wind_kmph and wind_kmph != "0":
            parts.append(f"wind {wind_kmph} km/h")
        return ", ".join(parts) + "."

    # Use connection recovery for HTTP client
    return connection_recovery.execute_with_recovery(
        "weather_wttr_in",
        _fetch_operation,
        connection_type=ConnectionType.HTTP_CLIENT,
        on_failure=lambda e: None  # Silently handle failure - will be dealt with by caller
    )


def _normalize_location(name: str) -> str:
    """ASCII-friendly city name for wttr.in."""
    if not name:
        return ""
    # Turkish dotted I / combining marks → plain ASCII where possible
    normalized = (
        name.replace("İ", "I")
        .replace("ı", "i")
        .replace("İ", "I")
        .replace("i̇", "i")
    )
    return normalized.strip()


def extract_location_from_command(text: str) -> str:
    """Best-effort city/location from a weather utterance."""
    lower = text.lower().strip()
    for prefix in ("hey jarvis ", "ok jarvis ", "jarvis "):
        if lower.startswith(prefix):
            lower = lower[len(prefix):].strip()
            text = text[len(prefix):].strip()

    strip_phrases = (
        "hava durumu",
        "hava nasıl",
        "hava nasil",
        "bugün hava",
        "bugun hava",
        "hava kaç derece",
        "hava kac derece",
        "what's the weather",
        "whats the weather",
        "how's the weather",
        "hows the weather",
        "how is the weather",
        "weather in",
        "weather for",
        "weather",
        "temperature in",
        "temperature",
        "sıcaklık",
        "sicaklik",
    )
    cleaned = lower
    for phrase in sorted(strip_phrases, key=len, reverse=True):
        cleaned = cleaned.replace(phrase, " ")
    cleaned = re.sub(r"\b(in|for|at|için|icin|bugün|bugun|today|now|şu an|su an)\b", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.-")
    if cleaned and len(cleaned) >= 2:
        return _normalize_location(cleaned.title())
    return ""


class WeatherTool(BaseTool):
    name = "weather.current"
    description = "Current weather for a location (wttr.in; empty = auto-detect)"
    permission_level = PermissionLevel.READ
    input_schema = {
        "location": {"type": "str", "required": False},
    }

    def __init__(self, *, default_location: str = "", timeout: float = DEFAULT_TIMEOUT) -> None:
        self._default_location = (default_location or "").strip()
        self._timeout = timeout

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        location = str(arguments.get("location") or "").strip() or self._default_location
        try:
            speech = fetch_weather(location, timeout=self._timeout)
        except urllib.error.URLError as err:
            return ToolResult(ok=False, error=f"Weather lookup failed: {err.reason}")
        except TimeoutError:
            return ToolResult(ok=False, error="Weather lookup timed out.")
        except Exception as err:
            return ToolResult(ok=False, error=f"Weather lookup failed: {err}")
        return ToolResult(ok=True, data=speech)