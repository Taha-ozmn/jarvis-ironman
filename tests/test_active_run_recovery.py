"""Active-run conflict → cancel + retry recovery for Cursor brain."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from cursor_sdk import AgentBusyError, CursorAgentError

from brain.cursor_brain import JarvisBrain


def _finished_run(text: str = "Tamam.") -> MagicMock:
    run = MagicMock()
    run.status = "running"
    run.supports.return_value = True
    run.iter_text.return_value = iter([])
    result = MagicMock()
    result.status = "finished"
    result.result = text
    run.wait.return_value = result
    return run


class ActiveRunRecoveryTests(unittest.TestCase):
    def _make_brain(self) -> JarvisBrain:
        brain = JarvisBrain(
            api_key="test",
            language="tr-TR",
            soft_timeout_sec=5.0,
            hard_timeout_sec=10.0,
            narrate=True,
            work_updates=False,
            stream_preview=False,
            background_on_timeout=False,
        )
        brain._ready.set()
        brain._agent = MagicMock()
        brain._agent.agent_id = "agent-test-1"
        brain._persona_pending = False
        return brain

    def test_is_active_run_error_detects_message_and_type(self) -> None:
        busy = AgentBusyError("Agent agent-abc already has active run")
        self.assertTrue(JarvisBrain._is_active_run_error(busy))
        wrapped = CursorAgentError("Agent agent-xyz already has active run")
        self.assertTrue(JarvisBrain._is_active_run_error(wrapped))
        other = CursorAgentError("network blip")
        self.assertFalse(JarvisBrain._is_active_run_error(other))

    def test_send_recovers_from_active_run_error(self) -> None:
        brain = self._make_brain()
        spoken: list[str] = []
        ok_run = _finished_run("Chrome is open.")
        calls = {"n": 0}

        def send_side_effect(*_a, **_k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise AgentBusyError("Agent agent-test-1 already has active run")
            return ok_run

        brain._agent.send.side_effect = send_side_effect

        with patch.object(brain, "_clear_agent_active_runs") as clear_mock:
            run = brain._send_with_active_run_recovery(
                "prompt",
                None,
                speak=spoken.append,
            )

        self.assertIs(run, ok_run)
        self.assertEqual(calls["n"], 2)
        clear_mock.assert_called_once()
        self.assertEqual(spoken, [brain._active_run_retry_message()])
        self.assertNotIn("Cursor bağlantı sorunu", " ".join(spoken))

    def test_execute_think_recovers_and_returns_answer(self) -> None:
        brain = self._make_brain()
        spoken: list[str] = []
        ok_run = _finished_run("Hazır.")
        calls = {"n": 0}

        def send_side_effect(*_a, **_k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise CursorAgentError(
                    "Agent agent-test-1 already has active run"
                )
            return ok_run

        brain._agent.send.side_effect = send_side_effect

        with patch.object(brain, "_clear_agent_active_runs"):
            result = brain._execute_think("merhaba", spoken.append, "simple")

        self.assertEqual(result, "Hazır.")
        self.assertEqual(calls["n"], 2)
        self.assertIn(brain._active_run_retry_message(), spoken)
        self.assertIn("Hazır.", spoken)
        self.assertIsNone(brain._active_run)

    def test_hard_timeout_cancels_sdk_run(self) -> None:
        brain = self._make_brain()
        run = MagicMock()
        run.status = "running"
        run.supports.return_value = True
        brain._active_run = run
        brain._cancel_tracked_run()
        run.cancel.assert_called_once()

    def test_think_with_narration_recovers_via_execute(self) -> None:
        brain = self._make_brain()
        spoken: list[str] = []

        def speak(msg: str) -> None:
            spoken.append(msg)

        ok_run = _finished_run("Done, sir.")
        calls = {"n": 0}

        def send_side_effect(*_a, **_k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise AgentBusyError("Agent agent-x already has active run")
            return ok_run

        brain._agent.send.side_effect = send_side_effect

        with patch.object(brain, "ensure_started"), patch.object(
            brain, "_clear_agent_active_runs"
        ):
            result = brain.think_with_narration("hava nasıl", speak)

        self.assertEqual(result, "Done, sir.")
        self.assertEqual(calls["n"], 2)
        self.assertIn(brain._active_run_retry_message(), spoken)
        self.assertNotIn("already has active run", " ".join(spoken))


if __name__ == "__main__":
    unittest.main()
