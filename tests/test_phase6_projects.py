"""Phase 6 — project registry + NL routing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.command_router import CommandRouter
from memory.database import Database
from projects.registry import ProjectRegistry


class ProjectRegistryTests(unittest.TestCase):
    def _yaml(self, root: Path, body: str) -> Path:
        path = root / "projects.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_seed_and_missing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "real_proj"
            existing.mkdir()
            yaml_path = self._yaml(
                root,
                f"""
projects:
  - key: real
    name: Real Project
    path: {existing}
    aliases: [real]
  - key: ghost
    name: Ghost Project
    path: {root / "does_not_exist"}
    aliases: [ghost]
""",
            )
            db = Database(root / "t.db")
            db.migrate()
            reg = ProjectRegistry(db, yaml_path=yaml_path)
            projects = reg.load()
            self.assertEqual(len(projects), 2)
            real = reg.get("real")
            ghost = reg.get("ghost")
            assert real is not None and ghost is not None
            self.assertTrue(real.exists)
            self.assertFalse(ghost.exists)
            self.assertFalse(ghost.available)

    def test_set_active_and_working_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj_dir = root / "app"
            proj_dir.mkdir()
            yaml_path = self._yaml(
                root,
                f"""
projects:
  - key: app
    name: App
    path: {proj_dir}
    aliases: [app]
""",
            )
            db = Database(root / "t.db")
            db.migrate()
            reg = ProjectRegistry(db, yaml_path=yaml_path)
            reg.load()
            active = reg.set_active("app")
            self.assertEqual(active.key, "app")
            self.assertEqual(reg.get_active().key, "app")
            self.assertEqual(reg.working_dir(), proj_dir.resolve())

    def test_working_dir_fallback_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            yaml_path = self._yaml(
                root,
                f"""
projects:
  - key: missing
    name: Missing
    path: {root / "nope"}
""",
            )
            db = Database(root / "t.db")
            db.migrate()
            reg = ProjectRegistry(db, yaml_path=yaml_path)
            reg.load()
            reg.set_active("missing")
            fallback = root / "fallback"
            fallback.mkdir()
            self.assertEqual(reg.working_dir(fallback=fallback), fallback)


class ProjectRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_list_projects(self) -> None:
        m = self.router.route("projeleri listele")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "project.list")

    def test_work_on_jettel(self) -> None:
        m = self.router.route("Jettel üzerinde çalış")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "project.set_active")
        self.assertIn("jettel", m.request.arguments["name"].lower())

    def test_analyze_repo_route(self) -> None:
        m = self.router.route("Bu repository'yi incele")
        self.assertEqual(m.request.tool_name, "dev.analyze_repo")


if __name__ == "__main__":
    unittest.main()
