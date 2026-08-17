"""Parallel diagnostics + storage seam + safe preset."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.app import JarvisOS
from core.parallel import run_parallel
from storage.backend import StorageBackend, backend_kind, open_sqlite


class ParallelTests(unittest.TestCase):
    def test_run_parallel_independent(self) -> None:
        def slow_a() -> str:
            time.sleep(0.05)
            return "a"

        def slow_b() -> str:
            time.sleep(0.05)
            return "b"

        t0 = time.perf_counter()
        out = run_parallel([("a", slow_a), ("b", slow_b)], max_workers=2)
        elapsed = time.perf_counter() - t0
        self.assertEqual(out["a"], "a")
        self.assertEqual(out["b"], "b")
        # Parallel should beat serial ~0.10s (allow slack on busy CI)
        self.assertLess(elapsed, 0.12)

    def test_diagnostics_parallel_includes_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {"jarvis2": {"db_path": "data/par.db"}},
                root=Path(tmp),
            )
            summary = os_core.diagnostics.summary()
            names = {c["name"] for c in summary["checks"]}
            self.assertIn("storage", names)
            self.assertIn("autonomy", names)
            self.assertIn("language", names)
            os_core.close()


class StorageSeamTests(unittest.TestCase):
    def test_sqlite_satisfies_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_sqlite(Path(tmp) / "t.db")
            self.assertTrue(isinstance(db, StorageBackend))
            self.assertEqual(backend_kind(db), "sqlite")
            db.migrate()
            row = db.fetchone("SELECT 1 AS ok")
            self.assertIsNotNone(row)
            db.close()


class SafePresetExists(unittest.TestCase):
    def test_preset_file(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config" / "presets" / "safe.yaml"
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("full_shell_access: false", text)
        self.assertIn("autonomy_level: 3", text)


if __name__ == "__main__":
    unittest.main()
