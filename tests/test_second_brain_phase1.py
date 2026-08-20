"""Second Brain Phase 1 — Fast/Deep router, trivial memory, personality, request_id."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config.loader import ensure_jarvis2_defaults, load_personality
from core.brain_router import BrainPath, BrainRouter
from core.latency_stats import LatencyStats
from memory.extractor import (
    ExtractedMemory,
    extract_and_save,
    extract_memories,
    is_trivial_utterance,
    score_importance,
)
from memory.database import Database
from memory.repository import MemoryRepository


class BrainRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = BrainRouter()

    def test_health_is_fast(self) -> None:
        d = self.router.decide("sistem durumu")
        self.assertEqual(d.path, BrainPath.FAST)
        self.assertEqual(d.tool_name, "system.health")

    def test_time_is_fast(self) -> None:
        d = self.router.decide("saat kaç")
        self.assertEqual(d.path, BrainPath.FAST)
        self.assertIn(d.tool_name, ("system.time", "system.date"))

    def test_open_app_is_fast(self) -> None:
        d = self.router.decide("chrome aç")
        self.assertEqual(d.path, BrainPath.FAST)
        self.assertEqual(d.tool_name, "system.open_app")

    def test_tabs_is_fast(self) -> None:
        d = self.router.decide("sekmelerde ne var")
        self.assertEqual(d.path, BrainPath.FAST)
        self.assertEqual(d.tool_name, "browser.list_tabs")

    def test_chat_is_deep(self) -> None:
        d = self.router.decide("Iron Man filmini nasıl buluyorsun")
        self.assertEqual(d.path, BrainPath.DEEP)
        self.assertIsNone(d.match)


class TrivialMemoryTests(unittest.TestCase):
    def test_trivial_skip(self) -> None:
        self.assertTrue(is_trivial_utterance("tamam"))
        self.assertTrue(is_trivial_utterance("ok"))
        self.assertTrue(is_trivial_utterance("Jarvis tamam"))
        self.assertEqual(extract_memories("tamam"), [])

    def test_preference_not_trivial(self) -> None:
        self.assertFalse(is_trivial_utterance("bana Taha diye hitap et"))
        found = extract_memories("bana Taha diye hitap et")
        self.assertTrue(found)
        self.assertGreaterEqual(score_importance(found[0]), 4)

    def test_extract_and_save_skips_trivial(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            db = Database(Path(tmp.name) / "m.db")
            db.migrate()
            repo = MemoryRepository(db)
            self.assertEqual(extract_and_save(repo, "tamam"), [])
            ids = extract_and_save(repo, "bana Emre diye hitap et")
            self.assertTrue(ids)
            mem = repo.get(ids[0])
            self.assertGreaterEqual(mem.importance, 4)
        finally:
            tmp.cleanup()

    def test_score_importance_profile(self) -> None:
        item = ExtractedMemory("x", category="profile", importance=2)
        self.assertEqual(score_importance(item), 5)


class PersonalityAndLatencyTests(unittest.TestCase):
    def test_personality_loads(self) -> None:
        p = load_personality()
        self.assertEqual(p.get("persona"), "professional")
        self.assertIn("efendim", (p.get("speech") or {}).get("forbid_phrases") or [])

    def test_ensure_defaults_wires_personality(self) -> None:
        cfg = ensure_jarvis2_defaults({"jarvis": {}, "jarvis2": {}})
        self.assertIn("personality", cfg)
        self.assertEqual(cfg["personality"]["language"], "tr-TR")

    def test_latency_request_id(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "lat.json"
            stats = LatencyStats(path)
            stats.record(
                "chrome aç",
                "tool",
                42.0,
                True,
                request_id="abc123",
                brain_path="fast",
            )
            recent = stats.recent(1)
            self.assertEqual(recent[0]["request_id"], "abc123")
            self.assertEqual(recent[0]["brain_path"], "fast")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
