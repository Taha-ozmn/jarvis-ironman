"""Voice/text classification for Level-3 confirmation replies."""

from __future__ import annotations

YES_PHRASES = (
    "evet",
    "onayla",
    "onaylıyorum",
    "onayliyorum",
    "tamam",
    "olur",
    "kabul",
    "yes",
    "yeah",
    "yep",
    "confirm",
    "approved",
    "approve",
    "do it",
    "go ahead",
    "proceed",
)

NO_PHRASES = (
    "hayır",
    "hayir",
    "iptal",
    "vazgeç",
    "vazgec",
    "reddet",
    "no",
    "nope",
    "cancel",
    "deny",
    "abort",
    "stop",
    "don't",
    "do not",
)


def classify_confirmation(text: str) -> str | None:
    """Return 'yes', 'no', or None."""
    lower = (text or "").strip().lower()
    if not lower:
        return None
    # Exact / short replies first
    if lower in YES_PHRASES or lower in {"e", "y", "ok", "okay"}:
        return "yes"
    if lower in NO_PHRASES or lower in {"n", "h"}:
        return "no"
    # Phrase containment for short utterances only
    if len(lower.split()) <= 4:
        if any(p == lower or lower.startswith(p + " ") for p in YES_PHRASES):
            return "yes"
        if any(p == lower or lower.startswith(p + " ") for p in NO_PHRASES):
            return "no"
    return None
