"""Unit tests for memory repository."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.database import Database
from memory.repository import MemoryRepository


class MemoryRepoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "test.db")
        self.db.migrate()
        self.repo = MemoryRepository(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_create_get_update_delete(self) -> None:
        mem = self.repo.create("Taha prefers British accent", key="voice", category="preference")
        self.assertGreater(mem.id, 0)
        got = self.repo.get(mem.id)
        self.assertIn("British", got.content)
        updated = self.repo.update(mem.id, content="Updated preference")
        self.assertEqual(updated.content, "Updated preference")
        self.repo.delete(mem.id)
        with self.assertRaises(KeyError):
            self.repo.get(mem.id)

    def test_keyword_search(self) -> None:
        self.repo.create("Open Spotify every morning", category="habit")
        self.repo.create("Workspace is jarvis-ironman", category="project")
        hits = self.repo.search("Spotify")
        self.assertEqual(len(hits), 1)
        self.assertIn("Spotify", hits[0].content)

    def test_upsert_by_key(self) -> None:
        a = self.repo.upsert_by_key("user_name", "Taha")
        b = self.repo.upsert_by_key("user_name", "Taha Emre")
        self.assertEqual(a.id, b.id)
        self.assertEqual(b.content, "Taha Emre")

    def test_local_embeddings_semantic(self) -> None:
        from memory.embeddings import embed_text, unpack

        mem = self.repo.create("Taha prefers British accent for JARVIS voice")
        self.repo.create("Shopping list: milk and eggs")
        blob = embed_text(mem.content)
        self.assertEqual(len(unpack(blob) or []), 256)
        hits = self.repo.search_semantic("British speaking style")
        self.assertTrue(any("British" in h.content for h in hits))


if __name__ == "__main__":
    unittest.main()
