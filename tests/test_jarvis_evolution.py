"""Evolution tests — hybrid retrieval, handle_turn, thinking trace."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from core.app import JarvisOS, TurnResult
from core.thinking_trace import ThinkingPhase, ThinkingTrace
from memory.database import Database
from memory.layers import MemoryLayers
from memory.repository import MemoryRepository
from memory.retrieval import HybridRetriever, parse_temporal_window


class HybridRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "m.db")
        self.db.migrate()
        self.repo = MemoryRepository(self.db)
        self.retriever = HybridRetriever(self.repo)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_temporal_parse_yesterday(self) -> None:
        window = parse_temporal_window("dün ne konuştuk")
        self.assertIsNotNone(window)
        assert window is not None
        self.assertEqual(window.label, "yesterday")

    def test_hybrid_ranks_relevant_memory(self) -> None:
        self.repo.create("Jettel project deployment notes", category="episodic", importance=4)
        self.repo.create("Weather was sunny", category="fact", importance=1)
        hits = self.retriever.retrieve("Jettel deployment", limit=3)
        self.assertTrue(hits)
        self.assertIn("Jettel", hits[0].content)

    def test_temporal_episodic_filter(self) -> None:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        today = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """
            INSERT INTO memories (key, content, category, importance, embedding, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (None, "Yesterday we fixed Chrome open bug", "episodic", 3, None, yesterday, yesterday),
        )
        self.db.execute(
            """
            INSERT INTO memories (key, content, category, importance, embedding, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (None, "Today we added hybrid memory", "episodic", 3, None, today, today),
        )
        self.db.commit()
        hits = self.retriever.retrieve_temporal("dün ne yaptık")
        self.assertTrue(hits)
        self.assertIn("Yesterday", hits[0].content)


class MemoryLayersEvolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "m.db")
        self.db.migrate()
        self.layers = MemoryLayers(MemoryRepository(self.db))

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_procedural_memory(self) -> None:
        mem = self.layers.record_procedural(
            "Run tests with: python -m unittest discover -s tests",
            key="workflow:tests",
        )
        self.assertIsNotNone(mem)
        hits = self.layers.search_procedural("how to run tests")
        self.assertTrue(hits)

    def test_temporal_speech_empty(self) -> None:
        speech = self.layers.temporal_speech("dün ne konuştuk", language="en-GB")
        self.assertIn("yesterday", speech.lower())


class ThinkingTraceTests(unittest.TestCase):
    def test_emit_and_label(self) -> None:
        seen: list[dict] = []
        trace = ThinkingTrace(on_update=lambda p: seen.append(p))
        trace.emit(ThinkingPhase.PLANNING, "Engaging neural core")
        self.assertTrue(seen)
        self.assertIn("Planning", trace.current_label())


class HandleTurnTests(unittest.TestCase):
    def test_handle_turn_time_fast_path(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        os_core = JarvisOS(
            {
                "jarvis": {"language": "en-GB", "user_name": "sir"},
                "jarvis2": {
                    "db_path": "data/ht.db",
                    "max_permission_level": 2,
                    "thinking_trace": True,
                },
            },
            root=root,
        )
        try:
            turn = os_core.handle_turn("what time is it")
            self.assertIsInstance(turn, TurnResult)
            self.assertTrue(turn.handled)
            self.assertIsNotNone(turn.speech)
        finally:
            os_core.db.close()
            tmp.cleanup()

    def test_handle_turn_chat_needs_brain(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        os_core = JarvisOS(
            {
                "jarvis": {"language": "en-GB"},
                "jarvis2": {"db_path": "data/ht2.db", "max_permission_level": 2},
            },
            root=root,
        )
        try:
            turn = os_core.handle_turn("explain quantum computing in simple terms")
            self.assertFalse(turn.handled)
            self.assertTrue(turn.brain_needed)
            self.assertEqual(turn.brain_path, "deep")
        finally:
            os_core.db.close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
