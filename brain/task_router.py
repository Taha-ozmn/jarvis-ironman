"""Classify voice commands by complexity — simple chat vs full project builds."""

from __future__ import annotations

COMPLEX_WORDS = (
    "mobil", "mobile", "uygulama", "app", "application",
    "website", "web sitesi", "web site", "proje", "project",
    "oluştur", "olustur", "create", "build", "geliştir", "gelistir",
    "develop", "implement", "yaz bana", "write me", "make me",
    "react native", "react-native", "flutter", "expo", "ios", "android",
    "full stack", "backend", "frontend", "api", "database", "veritabanı",
    "deploy", "docker", "migrate", "refactor", "scaffold", "bootstrap",
)

DEEP_WORDS = (
    "from scratch", "sıfırdan", "sifirdan", "tam kapsamlı", "tam kapsamli",
    "full jarvis", "complete system", "entire app", "tüm proje", "tum proje",
    "production", "enterprise", "multi-file", "architecture",
)

CODE_WORDS = (
    "kod", "code", "function", "class", "script", "python", "javascript",
    "typescript", "bug", "fix", "debug", "compile", "syntax", "hata",
    "dosya düzenle", "dosya duzenle", "yaz", "write", "edit file",
)


def classify_complexity(text: str) -> str:
    """Return 'simple', 'complex', or 'deep'."""
    lower = text.lower().strip()
    if any(w in lower for w in DEEP_WORDS):
        return "deep"
    if any(w in lower for w in COMPLEX_WORDS):
        return "complex"
    if any(w in lower for w in CODE_WORDS):
        return "complex"
    return "simple"


def task_timeout(
    text: str,
    *,
    simple: float = 90.0,
    complex_: float = 600.0,
    deep: float = 1200.0,
) -> float:
    level = classify_complexity(text)
    if level == "deep":
        return deep
    if level == "complex":
        return complex_
    return simple


def work_update_delays(
    complexity: str,
    *,
    fast: bool = False,
    interval_sec: float = 5.0,
    max_pings: int = 120,
) -> tuple[float, ...]:
    """Absolute delays for progress pings while the agent runs.

    Fast/simple paths return no pings (local tools finish under ~1s).
    Otherwise: first ping at ``interval_sec``, then every interval thereafter.
    """
    if fast and complexity == "simple":
        return ()
    interval = max(1.0, float(interval_sec or 5.0))
    count = max(1, int(max_pings))
    if complexity == "deep":
        count = max(count, 180)
    elif complexity == "complex":
        count = max(count, 90)
    else:
        count = min(count, 24)
    return tuple(interval * (i + 1) for i in range(count))
