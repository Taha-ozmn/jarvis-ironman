"""Post-merge hardening — brain soft-fail → degraded; bilingual confirm."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.app import JarvisOS
from core.degraded import get_degraded_mode


class BrainDegradedWireTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_degraded_mode().exit()

    def test_enter_degraded_on_brain_down(self) -> None:
        from main import JarvisCore

        with tempfile.TemporaryDirectory() as tmp:
            # Minimal fake core without full boot
            core = object.__new__(JarvisCore)
            core.os_v2 = JarvisOS(
                {"jarvis2": {"db_path": "data/bd.db"}},
                root=Path(tmp),
            )
            core.brain = MagicMock()
            core.brain.is_ready.return_value = False
            core._enter_degraded_brain_down("unit_test")
            self.assertTrue(get_degraded_mode().active)
            turn = core.os_v2.handle_turn(
                "write a long essay about arc reactors"
            )
            self.assertFalse(turn.allow_cursor)
            self.assertEqual(turn.brain_path, "degraded")
            core.os_v2.close()

    def test_ensure_brain_short_timeout(self) -> None:
        from main import JarvisCore

        core = object.__new__(JarvisCore)
        core.os_v2 = None
        core.brain = MagicMock()
        core.brain.is_ready.return_value = False
        core.brain.wait_ready.return_value = False
        core._set_status = MagicMock()
        core._enter_degraded_brain_down = MagicMock()
        msg = core._ensure_brain_or_degraded(timeout=0.1)
        self.assertIsNotNone(msg)
        self.assertIn("offline", (msg or "").lower())
        core.brain.wait_ready.assert_called()
        core._enter_degraded_brain_down.assert_called()


class ConfirmSpeechTests(unittest.TestCase):
    def test_tr_and_en(self) -> None:
        from main import JarvisCore

        core = object.__new__(JarvisCore)
        core.config = {"jarvis": {"language": "tr-TR"}}
        self.assertEqual(core._confirm_speech(True), "Onaylandı.")
        self.assertEqual(core._confirm_speech(False), "İptal edildi.")
        core.config = {"jarvis": {"language": "en-GB"}}
        self.assertEqual(core._confirm_speech(True), "Confirmed.")


if __name__ == "__main__":
    unittest.main()
