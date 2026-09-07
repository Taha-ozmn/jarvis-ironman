"""Continuous listening, pairing, and queued REST command tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.rest_api import dispatch_command
from security.ui_auth import PAIRING_HEADER, PairingTokenAuth
from ui.server import JarvisUI
from voice.self_listen_guard import SelfListenGuard


class _Speaker:
    is_busy = False
    is_speaking = False

    def wait_until_idle(self, timeout: float = 0.0) -> None:
        del timeout


class ContinuousListeningTests(unittest.TestCase):
    def test_processing_does_not_block_continuous_listening(self) -> None:
        guard = SelfListenGuard(
            _Speaker(),
            block_while_processing=False,
        )
        guard.set_processing(True)
        self.assertFalse(guard.blocked)

    def test_speaker_busy_still_blocks_tts_echo(self) -> None:
        speaker = _Speaker()
        guard = SelfListenGuard(speaker, block_while_processing=False)
        speaker.is_busy = True
        self.assertTrue(guard.blocked)


class PairingTokenTests(unittest.TestCase):
    def test_pairing_token_is_required_and_persists_stably(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "pairing.json"
            auth = PairingTokenAuth(state_path)
            request = SimpleNamespace(
                headers={PAIRING_HEADER: auth.token},
                query={},
                remote="192.168.1.20",
            )
            wrong = SimpleNamespace(
                headers={PAIRING_HEADER: "wrong-token"},
                query={},
                remote="192.168.1.20",
            )
            self.assertTrue(auth.authorized(request))
            self.assertFalse(auth.authorized(wrong))
            # The non-secret metadata file must never leak the raw token.
            self.assertNotIn(auth.token, state_path.read_text(encoding="utf-8"))
            # The token persists across restarts so the QR/phone link stays stable.
            reopened = PairingTokenAuth(state_path)
            self.assertEqual(reopened.token, auth.token)
            # The persisted secret is locked down to the owner only.
            self.assertEqual(auth.secret_path.stat().st_mode & 0o777, 0o600)


class RestQueueTests(unittest.TestCase):
    def test_rest_command_uses_shared_queue(self) -> None:
        queued: list[str] = []
        result = dispatch_command(
            "sistem durumunu kontrol et",
            enqueue_fn=lambda command: queued.append(command) or True,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["queued"])
        self.assertEqual(queued, ["sistem durumunu kontrol et"])

    def test_hud_queue_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ui = JarvisUI(
                mic_config={
                    "command_queue_maxsize": 1,
                    "pairing_state_path": str(Path(directory) / "pairing.json"),
                },
                host="127.0.0.1",
                open_browser=False,
            )
            ui._handle_message('{"type":"command","text":"first"}')
            ui._handle_message('{"type":"command","text":"second"}')
            self.assertEqual(ui.wait_for_command(timeout=0.01), "first")
            self.assertIsNone(ui.wait_for_command(timeout=0.01))

