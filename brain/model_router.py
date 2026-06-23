"""Route voice commands to the best Cursor model per task type."""

from __future__ import annotations

import re
from typing import Callable, Mapping, Optional

ACTION_WORDS = (
    "aç", "open", "launch", "başlat", "start", "göster", "show",
    "kapat", "close", "quit", "çalıştır", "run ", "execute",
    "yap", "git ", "create", "delete", "remove", "move", "copy",
    "play", "youtube", "spotify", "chrome", "safari", "terminal",
)
CODE_WORDS = (
    "code", "function", "bug", "fix", "refactor", "implement", "class",
    "python", "javascript", "typescript", "debug", "compile", "syntax",
    "kod", "hata", "fonksiyon", "dosya düzenle", "yaz", "script",
)
SYSTEM_WORDS = (
    "terminal", "shell", "command", "install", "uninstall", "delete",
    "chmod", "sudo", "execute", "run ", "çalıştır", "komut", "sistem",
    "permission", "process", "kill",
)
SEARCH_WORDS = (
    "search", "ara", "find", "lookup", "google", "bul ", "who is",
    "what is", "kim ", "nedir",
)

MODEL_ALIASES = {
    "auto": "auto",
    "composer": "composer-2.5",
    "composer-2": "composer-2.5",
    "flash": "gemini-3-flash",
    "gemini": "gemini-3-flash",
    "nano": "gpt-5.4-nano",
    "gpt": "gpt-5.4-nano",
    "default": "default",
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-4-6",
    "codex": "gpt-5.3-codex",
}


class ModelRouter:
    """Pick a Cursor model ID based on task category or manual override."""

    def __init__(
        self,
        models: Mapping[str, str],
        default: str,
        resolve: Callable[[str], str],
    ) -> None:
        self.models = dict(models)
        self.default = default
        self._resolve = resolve
        self.manual_override: Optional[str] = None
        self.manual_category: Optional[str] = None

    def classify(self, text: str) -> str:
        lower = text.lower()
        if any(w in lower for w in ACTION_WORDS):
            return "action"
        if any(w in lower for w in CODE_WORDS):
            return "code"
        if any(w in lower for w in SYSTEM_WORDS):
            return "system"
        if any(w in lower for w in SEARCH_WORDS):
            return "search"
        return "chat"

    def pick(self, category: str) -> str:
        if self.manual_override:
            return self._resolve(self.manual_override)
        if self.manual_category:
            raw = self.models.get(self.manual_category) or self.default
            return self._resolve(raw)
        raw = self.models.get(category) or self.models.get("default") or self.default
        return self._resolve(raw)

    def set_manual(self, model_or_alias: str) -> str:
        key = model_or_alias.lower().strip()
        if key in ("chat", "code", "system", "search", "action"):
            self.manual_category = key
            self.manual_override = None
            return self.pick(key)
        resolved = MODEL_ALIASES.get(key, model_or_alias)
        self.manual_override = self._resolve(resolved)
        self.manual_category = None
        return self.manual_override

    def clear_manual(self) -> None:
        self.manual_override = None
        self.manual_category = None

    def status_line(self) -> str:
        if self.manual_override:
            return f"manual model: {self.manual_override}"
        if self.manual_category:
            return f"manual mode: {self.manual_category} ({self.pick(self.manual_category)})"
        parts = ", ".join(f"{k}={v}" for k, v in self.models.items())
        return f"auto routing — {parts}"

    @staticmethod
    def parse_switch_command(text: str) -> Optional[str]:
        lower = text.lower().strip()
        patterns = [
            r"(?:use|switch to|set)\s+(\w[\w.-]*)",
            r"(\w[\w.-]*)\s+model",
            r"(chat|code|system|search)\s+mode",
            r"mod(?:el)?\s+(değiştir|degistir|change)\s+(\w+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, lower)
            if m:
                return m.group(1)
        if "fast mode" in lower or "hızlı mod" in lower:
            return "flash"
        if "code mode" in lower or "kod modu" in lower:
            return "code"
        return None
