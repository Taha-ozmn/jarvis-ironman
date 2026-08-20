"""Route voice commands to the best Cursor model per task type with fallback support."""

from __future__ import annotations

import re
import time
from typing import Callable, Mapping, Optional, Dict, List, Set


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
    "nemotron": "nvidia_nim/nvidia/nemotron-3-super-120b-a12b",
}


class ModelRouter:
    """Pick a Cursor model ID based on task category or manual override with fallback support."""

    def __init__(
        self,
        models: Mapping[str, str],
        default: str,
        resolve: Callable[[str], str],
        fallback_models: Optional[Mapping[str, List[str]]] = None,
        fallback_timeout: float = 300.0,  # 5 minutes before retrying a failed model
    ) -> None:
        self.models = dict(models)
        self.default = default
        self._resolve = resolve
        self.manual_override: Optional[str] = None
        self.manual_category: Optional[str] = None

        # Fallback configuration: category -> [fallback1, fallback2, ...]
        self._fallback_models: Dict[str, List[str]] = dict(fallback_models or {})

        # Track failed models and when they failed
        self._failed_models: Dict[str, float] = {}  # model -> timestamp of failure
        self._fallback_timeout = fallback_timeout

        # Track manual override failures separately
        self._failed_manual_override: Optional[float] = None

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

    def _is_model_failed(self, model: str) -> bool:
        """Check if a model is currently in failed state and should be skipped."""
        if model not in self._failed_models:
            return False

        # Check if enough time has passed to retry this model
        time_since_failure = time.time() - self._failed_models[model]
        if time_since_failure >= self._fallback_timeout:
            # Timeout expired, remove from failed list
            del self._failed_models[model]
            return False

        return True

    def _clear_model_failure(self, model: str) -> None:
        """Clear failure status for a model (called on success)."""
        if model in self._failed_models:
            del self._failed_models[model]

    def _record_model_failure(self, model: str) -> None:
        """Record that a model has failed."""
        self._failed_models[model] = time.time()

    def pick(self, category: str) -> str:
        if self.manual_override:
            # Check if manual override is failed
            if self._is_model_failed(self.manual_override):
                # Manual override failed, try to fall back to category-based selection
                pass  # Fall through to normal selection below
            else:
                return self._resolve(self.manual_override)

        if self.manual_category:
            raw = self.models.get(self.manual_category) or self.default
            if not self._is_model_failed(raw):
                return self._resolve(raw)
            # If manual category model failed, fall through to normal selection

        # Normal category-based selection with fallback
        raw = self.models.get(category) or self.models.get("default") or self.default

        # If primary model is not failed, use it
        if not self._is_model_failed(raw):
            return self._resolve(raw)

        # Primary model failed, try fallbacks for this category
        fallbacks = self._fallback_models.get(category, [])
        for fallback_model in fallbacks:
            if not self._is_model_failed(fallback_model):
                self._record_model_failure(raw)  # Record that primary failed
                return self._resolve(fallback_model)

        # If all fallbacks failed or no fallbacks, try to find any working model
        # First try default model if we haven't already
        if category != "default":
            default_model = self.models.get("default") or self.default
            if default_model != raw and not self._is_model_failed(default_model):
                self._record_model_failure(raw)  # Record that primary failed
                return self._resolve(default_model)

        # Last resort: return the primary model anyway (let higher layers handle failure)
        # but record that we think it's failed
        self._record_model_failure(raw)
        return self._resolve(raw)

    def set_manual(self, model_or_alias: str) -> str:
        key = model_or_alias.lower().strip()
        if key in ("chat", "code", "system", "search", "action"):
            self.manual_category = key
            self.manual_override = None
            # Clear any manual override failure when switching to category mode
            self._failed_manual_override = None
            return self.pick(key)
        resolved = MODEL_ALIASES.get(key, model_or_alias)
        self.manual_override = self._resolve(resolved)
        self.manual_category = None
        # Clear manual category when setting manual override
        self.manual_category = None
        return self.manual_override

    def clear_manual(self) -> None:
        self.manual_override = None
        self.manual_category = None
        self._failed_manual_override = None

    def status_line(self) -> str:
        if self.manual_override:
            failed_indicator = " [FAILED]" if self._is_model_failed(self.manual_override) else ""
            return f"manual model: {self.manual_override}{failed_indicator}"
        if self.manual_category:
            model = self.pick(self.manual_category)
            failed_indicator = " [FAILED]" if self._is_model_failed(model) else ""
            return f"manual mode: {self.manual_category} ({model}){failed_indicator}"
        parts = ", ".join(f"{k}={v}" for k, v in self.models.items())
        failed_models = [f"{k} (failed)" for k, v in self._failed_models.items()
                        if time.time() - v < self._fallback_timeout]
        if failed_models:
            parts += f" [failed: {', '.join(failed_models)}]"
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

    def record_failure(self, model: str) -> None:
        """Public method to record that a model has failed (to be called by higher layers)."""
        self._record_model_failure(model)

    def record_success(self, model: str) -> None:
        """Public method to record that a model has succeeded (to be called by higher layers)."""
        self._clear_model_failure(model)