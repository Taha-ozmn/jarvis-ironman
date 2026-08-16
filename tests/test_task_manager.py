"""Unit tests for task manager."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.task_manager import TaskManager
from memory.database import Database


class TaskManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "tasks.db")
        self.db.migrate()
        self.tasks = TaskManager(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_crud(self) -> None:
        task = self.tasks.create("Build JARVIS 2.0", description="Foundation", priority=3)
        self.assertEqual(task.status, "pending")
        updated = self.tasks.update(task.id, status="in_progress")
        # Legacy alias in_progress → running (Phase 4 state machine)
        self.assertEqual(updated.status, "running")
        listed = self.tasks.list(status="in_progress")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].status, "running")
        self.tasks.delete(task.id)
        self.assertEqual(self.tasks.list(), [])

    def test_invalid_status(self) -> None:
        task = self.tasks.create("x")
        with self.assertRaises(ValueError):
            self.tasks.update(task.id, status="nope")

    def test_empty_title(self) -> None:
        with self.assertRaises(ValueError):
            self.tasks.create("   ")


if __name__ == "__main__":
    unittest.main()
