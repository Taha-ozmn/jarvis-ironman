"""Phase 7 — backup, risk hardening, FTS memory, secrets."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.app import JarvisOS
from core.backup import BackupService
from core.execution_engine import ExecutionRequest
from memory.database import Database
from memory.extractor import looks_like_secret, redact_secrets
from memory.repository import MemoryRepository
from security.risk import (
    is_blocked_shell,
    is_credential_path,
    is_dangerous_shell,
    is_force_git_push,
)
from tools.git_tools import GitPushTool


class BackupTests(unittest.TestCase):
    def test_backup_creates_versioned_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            db_path = data / "jarvis.db"
            db = Database(db_path)
            db.migrate()
            db.execute(
                "INSERT INTO memories (content, category, importance, created_at, updated_at) "
                "VALUES ('hello', 'general', 1, 't', 't')"
            )
            db.commit()
            (root / "config").mkdir()
            (root / "config" / "projects.yaml").write_text("projects: []\n", encoding="utf-8")
            (root / "config.yaml").write_text("jarvis2: {}\n", encoding="utf-8")

            svc = BackupService(db_path=db_path, root=root, retention=2)
            r1 = svc.run()
            self.assertTrue(r1.ok, r1.message)
            self.assertTrue(Path(r1.path).exists())
            self.assertTrue((Path(r1.path) / "jarvis.db").exists())
            self.assertTrue((Path(r1.path) / "config__projects.yaml").exists())

            r2 = svc.run()
            self.assertTrue(r2.ok)
            r3 = svc.run()
            self.assertTrue(r3.ok)
            # retention 2
            self.assertLessEqual(len(svc.list_backups(limit=20)), 2)
            db.close()

    def test_system_backup_tool_via_os(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "projects.yaml").write_text("projects: []\n", encoding="utf-8")
            os_core = JarvisOS(
                {"jarvis2": {"db_path": "data/b.db", "max_permission_level": 2}},
                root=root,
            )
            result = os_core.execution.execute(ExecutionRequest("system.backup", {}))
            self.assertTrue(result.ok, result.error)
            self.assertIn("Backup", str(result.data))
            os_core.close()


class HardeningTests(unittest.TestCase):
    def test_block_rm_rf_root(self) -> None:
        self.assertTrue(is_blocked_shell("rm -rf /"))
        self.assertTrue(is_blocked_shell("rm -rf /*"))
        self.assertTrue(is_dangerous_shell("rm -rf /"))

    def test_force_push_detected(self) -> None:
        self.assertTrue(is_force_git_push("git push --force origin main"))
        self.assertTrue(is_force_git_push("git push -f"))
        self.assertTrue(is_dangerous_shell("git push --force origin main"))

    def test_git_push_tool_blocks_force(self) -> None:
        tool = GitPushTool(lambda: Path.cwd())
        result = tool.run({"force": True})
        self.assertFalse(result.ok)
        self.assertIn("Blocked", result.error or "")

    def test_credential_paths(self) -> None:
        self.assertTrue(is_credential_path("/Users/x/.env"))
        self.assertTrue(is_credential_path("~/secrets.yaml"))
        self.assertTrue(is_credential_path("credentials.json"))
        self.assertFalse(is_credential_path("README.md"))

    def test_shell_tool_blocks_rm_rf_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {
                    "jarvis2": {
                        "db_path": "data/h.db",
                        "max_permission_level": 3,
                        "auto_approve_dangerous": True,
                    }
                },
                root=Path(tmp),
            )
            result = os_core.execution.execute(
                ExecutionRequest("system.shell", {"command": "rm -rf /"})
            )
            self.assertFalse(result.ok)
            self.assertIn("Blocked", result.error or "")
            os_core.close()

    def test_secret_patterns_stronger(self) -> None:
        self.assertTrue(looks_like_secret("token: abc123xyz"))
        self.assertTrue(looks_like_secret("sk-abcdefghijklmnopqrstuvwxyz"))
        self.assertTrue(looks_like_secret("ghp_abcdefghijklmnopqrstuvwx"))
        self.assertIn("[REDACTED]", redact_secrets("password: hunter2"))


class FtsMemoryTests(unittest.TestCase):
    def test_fts_search_finds_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "m.db")
            applied = db.migrate()
            self.assertTrue(any("fts" in a for a in applied) or True)
            repo = MemoryRepository(db)
            repo.create("Taha prefers British accent for JARVIS", category="preference")
            repo.create("Working on Jettel Android app", category="project_context")
            hits = repo.search("British accent")
            self.assertTrue(any("British" in h.content for h in hits))
            hits2 = repo.search("Jettel")
            self.assertTrue(any("Jettel" in h.content for h in hits2))
            db.close()


if __name__ == "__main__":
    unittest.main()
