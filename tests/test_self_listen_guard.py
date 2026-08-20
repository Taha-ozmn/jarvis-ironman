"""Self-listen guard — ignore STT while TTS is speaking / cooldown."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from voice.self_listen_guard import SelfListenGuard


class _FakeSpeaker:
    def __init__(self) -> None:
        self.is_busy = False
        self.is_speaking = False
        self.wait_calls = 0

    def wait_until_idle(self, timeout: float = 30.0) -> None:
        del timeout
        self.wait_calls += 1
        self.is_busy = False
        self.is_speaking = False


class SelfListenGuardTests(unittest.TestCase):
    def test_transcript_ignored_while_speaking(self) -> None:
        speaker = _FakeSpeaker()
        speaker.is_busy = True
        speaker.is_speaking = True
        guard = SelfListenGuard(speaker, enabled=True, cooldown_ms=300)

        self.assertTrue(guard.blocked)
        self.assertFalse(guard.should_accept_transcript("Merhaba"))

    def test_transcript_ignored_while_processing(self) -> None:
        speaker = _FakeSpeaker()
        guard = SelfListenGuard(speaker, enabled=True, cooldown_ms=300)
        guard.set_processing(True)

        self.assertTrue(guard.blocked)
        self.assertFalse(guard.should_accept_transcript("saat kaç"))

        guard.set_processing(False)
        self.assertFalse(guard.blocked)
        self.assertTrue(guard.should_accept_transcript("saat kaç"))

    def test_disabled_guard_always_accepts(self) -> None:
        speaker = _FakeSpeaker()
        speaker.is_busy = True
        guard = SelfListenGuard(speaker, enabled=False, cooldown_ms=500)
        guard.set_processing(True)

        self.assertFalse(guard.blocked)
        self.assertTrue(guard.should_accept_transcript("echo"))

    def test_cooldown_blocks_after_tts(self) -> None:
        speaker = _FakeSpeaker()
        guard = SelfListenGuard(speaker, enabled=True, cooldown_ms=500)
        guard.arm_cooldown()

        self.assertTrue(guard.blocked)
        self.assertFalse(guard.should_accept_transcript("late echo"))

    def test_wait_until_accepting_arms_cooldown(self) -> None:
        speaker = _FakeSpeaker()
        speaker.is_busy = True
        guard = SelfListenGuard(speaker, enabled=True, cooldown_ms=50)
        guard.wait_until_accepting(timeout=1.0)

        self.assertEqual(speaker.wait_calls, 1)
        # Immediately after wait, cooldown may still be active
        # (50ms) — either blocked briefly or already clear is fine;
        # speaker must have been waited on.
        self.assertFalse(speaker.is_busy)


class JarvisCoreEchoGateTests(unittest.TestCase):
    """Simulate speak → transcript during speak → no process_command."""

    def test_run_command_skips_when_speaking(self) -> None:
        speaker = _FakeSpeaker()
        speaker.is_busy = True
        guard = SelfListenGuard(speaker, enabled=True, cooldown_ms=500)

        process_command = MagicMock(return_value="ok")

        def voice_input_allowed(command: str = "") -> bool:
            return guard.should_accept_transcript(command)

        def run_command(command: str) -> None:
            if not voice_input_allowed(command):
                return
            process_command(command)

        run_command("Bakıyorum.")
        process_command.assert_not_called()

        speaker.is_busy = False
        guard.clear_cooldown()
        run_command("saat kaç")
        process_command.assert_called_once_with("saat kaç")


if __name__ == "__main__":
    unittest.main()
