"""Memory recall injection into brain prompt path (no Cursor SDK / edge-tts)."""

from __future__ import annotations

import sys
import types
import unittest


def _install_fakes() -> None:
    if "cursor_sdk" not in sys.modules:
        fake = types.ModuleType("cursor_sdk")

        class _Dummy:
            pass

        fake.Agent = _Dummy
        fake.Cursor = _Dummy
        fake.CursorAgentError = type("CursorAgentError", (Exception,), {})
        fake.LocalAgentOptions = _Dummy
        fake.NetworkError = type("NetworkError", (Exception,), {})
        fake.SandboxOptions = _Dummy
        fake.SendOptions = _Dummy
        sys.modules["cursor_sdk"] = fake

    if "edge_tts" not in sys.modules:
        sys.modules["edge_tts"] = types.ModuleType("edge_tts")


class MemoryRecallPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _install_fakes()
        for name in list(sys.modules):
            if name == "brain" or name.startswith("brain.") or name == "voice" or name.startswith("voice."):
                del sys.modules[name]
        from brain.cursor_brain import JarvisBrain  # noqa: WPS433

        cls.JarvisBrain = JarvisBrain

    def test_prompt_includes_recall(self) -> None:
        brain = self.JarvisBrain(
            api_key="test",
            skip_model_list=True,
            conversation_turns=2,
        )
        brain.set_memory_recall(
            lambda q: (
                "[LONG-TERM MEMORY — use only if relevant]\n- (preference) tea"
                if "drink" in q.lower() or "tea" in q.lower()
                else ""
            )
        )
        prompt = brain._wrap_user_message("What is my favourite drink?")
        self.assertIn("LONG-TERM MEMORY", prompt)
        self.assertIn("tea", prompt)

    def test_prompt_skips_empty_recall(self) -> None:
        brain = self.JarvisBrain(api_key="test", skip_model_list=True)
        brain.set_memory_recall(lambda _q: "")
        prompt = brain._wrap_user_message("Hello there")
        self.assertNotIn("LONG-TERM MEMORY", prompt)


if __name__ == "__main__":
    unittest.main()
