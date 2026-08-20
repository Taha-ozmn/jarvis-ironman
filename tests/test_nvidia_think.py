"""NVIDIA DeepBrain path — unit tests (no live API)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from brain.cursor_brain import JarvisBrain
from brain.nvidia_llm_provider import NVIDIAProvider, normalize_nvidia_model


class NormalizeModelTests(unittest.TestCase):
    def test_strips_nvidia_nim_prefix(self) -> None:
        self.assertEqual(
            normalize_nvidia_model("nvidia_nim/nvidia/nemotron-3-super-120b-a12b"),
            "nvidia/nemotron-3-super-120b-a12b",
        )

    def test_passthrough(self) -> None:
        self.assertEqual(
            normalize_nvidia_model("nvidia/llama-3.1-nemotron-70b-instruct"),
            "nvidia/llama-3.1-nemotron-70b-instruct",
        )


class NvidiaThinkPathTests(unittest.TestCase):
    def test_think_uses_nvidia_provider_without_agent(self) -> None:
        brain = JarvisBrain(
            api_key="test-key",
            language="en-GB",
            llm_provider="nvidia",
            skip_model_list=True,
            narrate=False,
            work_updates=False,
            think_timeout=5.0,
        )
        provider = MagicMock(spec=NVIDIAProvider)
        provider.complete.return_value = "Chrome is open, sir."
        brain._nvidia_provider = provider
        brain._ready.set()
        brain.llm_provider = "nvidia"
        brain._agent = None

        spoken: list[str] = []
        result = brain.think_with_narration("open chrome", spoken.append)
        self.assertIn("Chrome", result)
        provider.complete.assert_called_once()
        # narrate=False → speak not required
        self.assertEqual(spoken, [])

    def test_think_raises_when_neither_backend_ready(self) -> None:
        brain = JarvisBrain(
            api_key="test-key",
            language="en-GB",
            llm_provider="nvidia",
            skip_model_list=True,
        )
        brain._ready.set()
        brain._agent = None
        brain._nvidia_provider = None
        with self.assertRaises(RuntimeError):
            brain.think("hello")


if __name__ == "__main__":
    unittest.main()
