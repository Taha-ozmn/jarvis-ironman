"""Error classification + user-safe recovery speech (Phase 1 Stability).

Never surface raw phrases like "Could not open" to the user.
Developer logs keep the real exception / stderr.
"""

from __future__ import annotations

import logging
import re
import time
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# Hard caps — never infinite retry
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_BACKOFF_SEC = 0.25


class ErrorClass(str, Enum):
    NETWORK = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    AUTH = "AUTH_ERROR"
    TOOL = "TOOL_ERROR"
    MODEL = "MODEL_ERROR"
    FILE = "FILE_ERROR"
    PERMISSION = "PERMISSION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN_ERROR"


_EN_COULD_NOT_OPEN = re.compile(
    r"(?i)^could\s+not\s+open\s+[«\"]?(.+?)[»\"]?\s*\.?$"
)
_RETRYABLE = frozenset(
    {
        ErrorClass.NETWORK,
        ErrorClass.TIMEOUT,
        ErrorClass.TOOL,
        ErrorClass.UNKNOWN,
    }
)


def classify_error(message: str, *, exc: Optional[BaseException] = None) -> ErrorClass:
    text = (message or "").lower()
    if exc is not None:
        name = type(exc).__name__.lower()
        if "timeout" in name:
            return ErrorClass.TIMEOUT
        if "permission" in name:
            return ErrorClass.PERMISSION
        if "filenotfound" in name:
            return ErrorClass.FILE
    if any(w in text for w in ("timed out", "timeout", "deadline")):
        return ErrorClass.TIMEOUT
    if any(w in text for w in ("permission denied", "not authorized", "confirmation")):
        return ErrorClass.PERMISSION
    if any(w in text for w in ("network", "connection", "could not connect", "bridge")):
        return ErrorClass.NETWORK
    if any(w in text for w in ("auth", "api key", "unauthorized", "401", "403")):
        return ErrorClass.AUTH
    if any(w in text for w in ("model unavailable", "neural link", "cursor")):
        return ErrorClass.MODEL
    if any(w in text for w in ("not found", "no such file", "missing", "unknown app")):
        return ErrorClass.NOT_FOUND
    if any(w in text for w in ("could not open", "failed to open", "tool failed")):
        return ErrorClass.TOOL
    return ErrorClass.UNKNOWN


def is_retryable(error_class: ErrorClass, message: str = "") -> bool:
    text = (message or "").lower()
    # Permanent failures — never burn retries
    if any(
        w in text
        for w in (
            "required",
            "not available",
            "not implemented",
            "permission denied",
            "confirmation",
            "refusing",
            "blocked",
            "which app",
            "is a stub",
        )
    ):
        return False
    # Short exception-like messages (e.g. "explode") — do not retry
    if error_class is ErrorClass.UNKNOWN and len(text.split()) <= 4:
        if not any(w in text for w in ("timeout", "network", "connect", "temporar")):
            return False
    return error_class in _RETRYABLE


def backoff_seconds(attempt: int, *, base: float = DEFAULT_BASE_BACKOFF_SEC) -> float:
    """Exponential backoff for attempt index 0, 1, 2…"""
    return float(base) * (2 ** max(0, int(attempt)))


def sleep_backoff(attempt: int, *, base: float = DEFAULT_BASE_BACKOFF_SEC) -> None:
    delay = backoff_seconds(attempt, base=base)
    if delay > 0:
        time.sleep(delay)


def user_safe_speech(
    message: str,
    *,
    target: str = "",
    error_class: Optional[ErrorClass] = None,
    language: str = "en-GB",
) -> str:
    """Turn technical failures into calm, actionable speech."""
    raw = (message or "").strip()
    cls = error_class or classify_error(raw)
    lang = (language or "en-GB").lower()
    tr = lang.startswith("tr")

    m = _EN_COULD_NOT_OPEN.match(raw)
    if m and not target:
        target = m.group(1).strip().strip("\"'«»")

    name = (target or "").strip().strip("\"'«»")
    if name and (
        "could not open" in raw.lower()
        or "couldn't launch" in raw.lower()
        or cls is ErrorClass.TOOL
    ):
        if tr:
            return (
                f"«{name}» açılamadı. Uygulama adını netleştirir misin, "
                f"yoksa başka bir yoldan denemememi ister misin?"
            )
        return (
            f"I couldn't launch «{name}». "
            f"Confirm the app name, or I can try another method."
        )

    if cls is ErrorClass.TIMEOUT:
        return (
            "İşlem zaman aşımına uğradı; kısa bir bekleyişten sonra yeniden deniyorum."
            if tr
            else "That timed out — I'll retry shortly with a different approach."
        )
    if cls is ErrorClass.NETWORK:
        return (
            "Bağlantı kurulamadı. Yerel araçlarla devam ediyorum; ağ düzelince tekrar denerim."
            if tr
            else "I couldn't reach the network service. Local tools still work; I'll retry when the link is back."
        )
    if cls is ErrorClass.PERMISSION:
        # Keep "Permission denied" token for callers/tests/HUD filters
        if tr:
            return "Permission denied — bu işlem için daha yüksek izin veya onay gerekiyor."
        return (
            "Permission denied — this needs a higher clearance or your confirmation."
        )
    if cls is ErrorClass.NOT_FOUND:
        return (
            "Hedefi bulamadım. Adı biraz daha net söylemen yeterli."
            if tr
            else "I couldn't find that target. A clearer name should do it."
        )
    if cls is ErrorClass.MODEL:
        return (
            "Ana model şu anda yanıt vermiyor. Yerel araçlar açık; yedek yola geçiyorum."
            if tr
            else "The primary model isn't responding. Local tools are still available; switching to a fallback path."
        )

    # Preserve already-actionable tool errors (stubs, exceptions, validation)
    if not re.match(r"(?i)^(could not|failed to|unable to|connection failed)\b", raw):
        if len(raw) > 220:
            return raw[:217] + "…"
        return raw

    # Strip robotic English failure openers without dumping internals
    cleaned = re.sub(
        r"(?i)^(could not|failed to|unable to|tool failed[:\s]*)\s*",
        "",
        raw,
    ).strip(" .")
    if not cleaned or cleaned.lower() == raw.lower():
        return (
            "İşlem başarısız oldu. Durumu kontrol edip alternatif bir yol deniyorum."
            if tr
            else "That didn't work. I'm checking the failure and trying an alternative."
        )
    if len(cleaned) > 160:
        cleaned = cleaned[:157] + "…"
    if tr:
        return f"Bir sorun çıktı: {cleaned}"
    return f"Something went wrong: {cleaned}"


def log_failure(
    tool: str,
    message: str,
    *,
    error_class: Optional[ErrorClass] = None,
    attempt: int = 0,
    exc: Optional[BaseException] = None,
) -> ErrorClass:
    cls = error_class or classify_error(message, exc=exc)
    logger.warning(
        "tool_failure tool=%s class=%s attempt=%s detail=%s",
        tool,
        cls.value,
        attempt,
        (message or "")[:300],
        exc_info=exc is not None,
    )
    return cls
