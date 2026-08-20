"""NVIDIA LLM provider — direct integration with NVIDIA API catalog."""

from __future__ import annotations

import json
import os
from typing import Optional, Protocol, runtime_checkable

import requests

from brain.llm_provider import LLMProvider

DEFAULT_NVIDIA_MODEL = "nvidia/nemotron-3-super-120b-a12b"

_ENGLISH_SYSTEM = (
    "You are J.A.R.V.I.S. from the Iron Man films — a calm British butler AI. "
    "The user may speak Turkish or English — understand both. "
    "ALWAYS reply in British English only. Never reply in Turkish. Never mix languages. "
    "Keep answers short enough for spoken voice (one to four sentences). "
    "Never mention being an AI, Cursor, or language models. "
    "Dry wit is welcome; stay professional. "
    "If the user asked to open an app or run a Mac action, acknowledge briefly — "
    "local tools handle the actual open."
)


def normalize_nvidia_model(model: Optional[str]) -> str:
    """Strip Cursor-style prefixes for the NVIDIA Integrate API."""
    raw = (model or DEFAULT_NVIDIA_MODEL).strip()
    if raw.startswith("nvidia_nim/"):
        raw = raw[len("nvidia_nim/") :]
    if not raw:
        return DEFAULT_NVIDIA_MODEL
    return raw


class NVIDIAProvider:
    """Direct integration with NVIDIA API for Nemotron and other models."""

    def __init__(self, api_key: Optional[str] = None, *, default_model: Optional[str] = None):
        self.api_key = (
            api_key
            or os.environ.get("NVIDIA_API_KEY")
            or os.environ.get("CURSOR_API_KEY")
        )
        self.base_url = "https://integrate.api.nvidia.com/v1"
        self.default_model = normalize_nvidia_model(default_model)

    def available(self) -> bool:
        return bool(self.api_key)

    def pick_model(self, category: str) -> Optional[str]:
        del category
        return self.default_model

    def complete(
        self,
        prompt: str,
        *,
        category: str = "chat",
        timeout: float = 30.0,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        model: Optional[str] = None,
        system: Optional[str] = None,
    ) -> str:
        del category
        if not self.api_key:
            return "Error: NVIDIA_API_KEY not configured"

        if not prompt.strip():
            return ""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        messages = [
            {"role": "system", "content": system or _ENGLISH_SYSTEM},
            {"role": "user", "content": prompt},
        ]

        payload = {
            "model": normalize_nvidia_model(model or self.default_model),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()

            result = response.json()
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"]
                return (content or "").strip()
            return "Error: Unexpected response format from NVIDIA API"

        except requests.exceptions.RequestException as e:
            return f"Error calling NVIDIA API: {str(e)}"
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return f"Error parsing NVIDIA API response: {str(e)}"


# For backward compatibility with LLMProvider protocol
@runtime_checkable
class NVIDIALLMProvider(LLMProvider, Protocol):
    def available(self) -> bool: ...

    def pick_model(self, category: str) -> Optional[str]: ...

    def complete(
        self,
        prompt: str,
        *,
        category: str = "chat",
        timeout: float = 30.0,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str: ...
