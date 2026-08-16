"""DecisionEngine wired into handle_turn + desktop confirm bridge."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.app import JarvisOS
from core.decision import BrainPath, DecisionEngine, decide_turn
from core.degraded import get_degraded_mode
from ui.desktop import DesktopConfirmBridge


class DecisionEngineWireTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_degraded_mode().exit()

    def test_engine_on_os(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {"jarvis2": {"db_path": "data/dec.db"}},
                root=Path(tmp),
            )
            try:
                self.assertIsInstance(os_core.decision, DecisionEngine)
                turn = os_core.handle_turn("saat kaç")
                self.assertFalse(turn.allow_cursor)
                self.assertIsNotNone(os_core._last_decision)
            finally:
                os_core.close()

    def test_degraded_path(self) -> None:
        eng = DecisionEngine()
        get_degraded_mode().enter("test")
        d = eng.decide("explain quantum computing in depth")
        self.assertFalse(d.allow_cursor)
        self.assertEqual(d.preferred_path, BrainPath.DEGRADED)
        speech = eng.fallback_speech(d, "explain")
        self.assertIn("offline", speech.lower())


class DesktopConfirmBridgeTests(unittest.TestCase):
    def test_focus_calls_window(self) -> None:
        bridge = DesktopConfirmBridge()
        window = MagicMock()
        bridge.bind(window)
        bridge.on_confirm_request({"id": "abc", "action": "wipe"})
        window.restore.assert_called()
        window.show.assert_called()
        window.evaluate_js.assert_called()

    def test_unbound_safe(self) -> None:
        DesktopConfirmBridge().on_confirm_request({})


if __name__ == "__main__":
    unittest.main()
