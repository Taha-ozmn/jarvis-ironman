"""Intent + Jarvis mode classification (master spec §6, §72, §81)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class JarvisMode(str, Enum):
    CHAT = "chat"
    CODE = "code"
    RESEARCH = "research"
    AUTOMATION = "automation"
    SYSTEM = "system"
    PROJECT = "project"
    FOCUS = "focus"
    AUTONOMOUS = "autonomous"


class Intent(str, Enum):
    CHAT = "CHAT"
    PROJECT_ANALYSIS = "PROJECT_ANALYSIS"
    BUG_FIND = "BUG_FIND"
    BUG_FIX = "BUG_FIX"
    RUN_TESTS = "RUN_TESTS"
    GIT_STATUS = "GIT_STATUS"
    CONTINUE = "CONTINUE"
    EDIT_FILE = "EDIT_FILE"
    SYSTEM_STATUS = "SYSTEM_STATUS"
    RETRY = "RETRY"
    STOP = "STOP"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ClassifiedIntent:
    intent: Intent
    mode: JarvisMode
    confidence: float
    phrase: str = ""


def _has_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(p in text for p in phrases)


def classify_intent(command: str) -> ClassifiedIntent:
    """Keyword+phrase classifier used before tool routing."""
    lower = (command or "").strip().lower()
    for prefix in ("hey jarvis ", "ok jarvis ", "jarvis, ", "jarvis "):
        if lower.startswith(prefix):
            lower = lower[len(prefix) :].strip()

    # Exact stop — never steal "durum"
    if lower in ("dur", "stop", "iptal", "cancel") or _has_any(
        lower,
        (
            "bu işi durdur",
            "bu isi durdur",
            "stop that",
            "stop the task",
            "cancel the task",
        ),
    ):
        return ClassifiedIntent(Intent.STOP, JarvisMode.FOCUS, 0.95, lower)

    if _has_any(
        lower,
        ("dün", "dun ", "yesterday", "kaldığımız yerden", "kaldigimiz yerden"),
    ) and _has_any(lower, ("devam", "continue", "left off")):
        return ClassifiedIntent(Intent.CONTINUE, JarvisMode.FOCUS, 0.92, lower)

    checks: list[tuple[Intent, JarvisMode, tuple[str, ...]]] = [
        (Intent.PAUSE, JarvisMode.FOCUS, ("pause", "duraklat", "beklet")),
        (
            Intent.RESUME,
            JarvisMode.FOCUS,
            ("resume", "devam et", "kaldığı yerden", "kaldigi yerden"),
        ),
        (
            Intent.RETRY,
            JarvisMode.SYSTEM,
            (
                "tekrar dene",
                "retry",
                "try again",
                "başarısız olan işlemi tekrar dene",
                "basarisiz olan islemi tekrar dene",
                "retry that",
                "retry the last",
            ),
        ),
        (
            Intent.SYSTEM_STATUS,
            JarvisMode.SYSTEM,
            (
                "sistem durumunu kontrol et",
                "sistem durumu",
                "system status",
                "jarvis status",
                "sağlık kontrol",
                "saglik kontrol",
            ),
        ),
        (
            Intent.GIT_STATUS,
            JarvisMode.CODE,
            (
                "git durumunu kontrol et",
                "git durum",
                "git status",
                "repo status",
            ),
        ),
        (
            Intent.RUN_TESTS,
            JarvisMode.CODE,
            (
                "testleri çalıştır",
                "testleri calistir",
                "run tests",
                "run the tests",
            ),
        ),
        (
            Intent.BUG_FIX,
            JarvisMode.CODE,
            (
                "hatayı düzelt",
                "hatayi duzelt",
                "fix the error",
                "fix this bug",
                "fix the bug",
                "bu hatayı düzelt",
                "bu hatayi duzelt",
            ),
        ),
        (
            Intent.BUG_FIND,
            JarvisMode.CODE,
            (
                "hatayı bul",
                "hatayi bul",
                "bu hatayı bul",
                "bu hatayi bul",
                "find this bug",
                "find the error",
                "find the bug",
            ),
        ),
        (
            Intent.PROJECT_ANALYSIS,
            JarvisMode.PROJECT,
            (
                "projeyi analiz et",
                "şu projeye bir bak",
                "su projeye bir bak",
                "analyze the project",
                "analyse the project",
                "analyze project",
                "projeyi incele",
            ),
        ),
        (
            Intent.EDIT_FILE,
            JarvisMode.CODE,
            (
                "bu dosyayı düzenle",
                "bu dosyayi duzenle",
                "edit this file",
                "edit the file",
                "dosyayı düzenle",
                "dosyayi duzenle",
            ),
        ),
    ]
    for intent, mode, phrases in checks:
        if intent == Intent.RESUME and _has_any(lower, ("dün", "dun ", "yesterday")):
            continue
        if _has_any(lower, phrases):
            return ClassifiedIntent(intent, mode, 0.9, lower)

    if lower in ("duraklat", "pause"):
        return ClassifiedIntent(Intent.PAUSE, JarvisMode.FOCUS, 0.9, lower)
    if lower in ("resume", "devam et"):
        return ClassifiedIntent(Intent.RESUME, JarvisMode.FOCUS, 0.85, lower)
    return ClassifiedIntent(Intent.UNKNOWN, JarvisMode.CHAT, 0.3, lower)
