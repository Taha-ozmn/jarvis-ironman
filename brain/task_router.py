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


def work_update_delays(complexity: str) -> tuple[float, ...]:
    """Periodic status pings while the agent runs."""
    if complexity == "deep":
        return (2.5, 7.0, 15.0, 30.0, 60.0, 90.0, 120.0, 180.0, 240.0, 300.0)
    if complexity == "complex":
        return (2.5, 7.0, 15.0, 30.0, 60.0, 90.0, 120.0)
    return (2.5, 7.0)
