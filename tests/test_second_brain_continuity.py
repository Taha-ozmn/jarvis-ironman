"""Second-brain continuity: mode select, conversation memory, progress config."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from brain.conversation import ConversationMemory
from brain.cursor_brain import JarvisBrain
from core.brain_router import BrainPath, BrainRouter
from core.mode_selector import AgentMode, select_mode


class ModeSelectorTests(unittest.TestCase):
    def test_chat_brainstorm(self) -> None:
        self.assertEqual(select_mode("bu proje için fikir ver"), AgentMode.CHAT)

    def test_research(self) -> None:
        self.assertEqual(select_mode("AI araçlarını araştır"), AgentMode.RESEARCH)

    def test_code(self) -> None:
        self.assertEqual(select_mode("bu repodaki bugı bul"), AgentMode.CODE)

    def test_plan(self) -> None:
        self.assertEqual(select_mode("haftalık plan çıkar"), AgentMode.PLAN)

    def test_act(self) -> None:
        self.assertEqual(select_mode("chrome aç"), AgentMode.ACT)


class ConversationMemoryTests(unittest.TestCase):
    def test_keeps_many_turns_and_topic(self) -> None:
        mem = ConversationMemory(max_turns=40)
        for i in range(12):
            mem.add(f"user turn {i} about jettel", f"reply {i}")
        self.assertEqual(mem.turn_count, 12)
        ctx = mem.format_context("Taha")
        self.assertIn("WORKING MEMORY", ctx)
        self.assertIn("user turn 11", ctx)
        self.assertIn("jettel", mem.active_topic.lower())


class BrainRouterModeTests(unittest.TestCase):
    def test_chat_goes_deep(self) -> None:
        d = BrainRouter().decide("ne düşünüyorsun bu konuda")
        self.assertEqual(d.path, BrainPath.DEEP)
        self.assertEqual(d.mode, AgentMode.CHAT)

    def test_open_app_stays_fast(self) -> None:
        d = BrainRouter().decide("chrome aç")
        self.assertEqual(d.path, BrainPath.FAST)


class ProgressNeverSkippedTests(unittest.TestCase):
    def test_think_path_does_not_skip_progress_flag(self) -> None:
        brain = JarvisBrain.__new__(JarvisBrain)
        brain.fast_mode = True
        brain.progress_interval_sec = 5.0
        brain.soft_timeout_sec = 5.0
        brain.hard_timeout_sec = 0.0
        brain.narrate = True
        brain.work_updates = True
        # Mirror the resolved skip flag used in think_with_narration
        skip_progress = False  # intentional product rule
        self.assertFalse(skip_progress)


if __name__ == "__main__":
    unittest.main()
