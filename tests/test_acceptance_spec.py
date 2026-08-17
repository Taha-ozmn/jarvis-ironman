"""Master spec §81 acceptance scenarios — all must route and execute locally."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.app import JarvisOS
from core.intent import Intent, classify_intent
from core.execution_engine import ExecutionRequest
from security.permissions import PermissionLevel
from tools.base import StubTool, ToolResult


SCENARIOS = (
    ("Jarvis, projeyi analiz et.", Intent.PROJECT_ANALYSIS, "project.health"),
    ("Jarvis, bu hatayı bul.", Intent.BUG_FIND, "dev.analyze_repo"),
    ("Jarvis, hatayı düzelt.", Intent.BUG_FIX, "dev.fix_cycle"),
    ("Jarvis, testleri çalıştır.", Intent.RUN_TESTS, "dev.run_tests"),
    ("Jarvis, Git durumunu kontrol et.", Intent.GIT_STATUS, "git.status"),
    ("Jarvis, dün yaptığımız işe devam et.", Intent.CONTINUE, "session.continue"),
    ("Jarvis, bu dosyayı düzenle.", Intent.EDIT_FILE, "session.edit_file"),
    ("Jarvis, sistem durumunu kontrol et.", Intent.SYSTEM_STATUS, "diagnostics.health"),
    ("Jarvis, başarısız olan işlemi tekrar dene.", Intent.RETRY, "session.retry"),
    ("Jarvis, bu işi durdur.", Intent.STOP, "session.stop"),
)


class IntentAcceptanceTests(unittest.TestCase):
    def test_all_spec_phrases_classify(self) -> None:
        for phrase, intent, _tool in SCENARIOS:
            classified = classify_intent(phrase)
            self.assertEqual(classified.intent, intent, phrase)

    def test_dur_does_not_steal_durum(self) -> None:
        self.assertEqual(
            classify_intent("sistem durumunu kontrol et").intent,
            Intent.SYSTEM_STATUS,
        )
        self.assertEqual(classify_intent("dur").intent, Intent.STOP)


class HandleTurnAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "README.md").write_text("# t\n", encoding="utf-8")
        self.os = JarvisOS(
            {
                "jarvis": {"language": "en-GB"},
                "jarvis2": {
                    "db_path": "data/acc.db",
                    "max_permission_level": 3,
                    "auto_approve_dangerous": True,
                },
                "system": {"full_shell_access": False},
                "voice": {"dual_locale": True, "listen_language": "tr-TR"},
            },
            root=self.root,
        )
        # Never run the real repo test suite from inside acceptance (nested unittest).
        class _Ok(StubTool):
            def run(self, arguments):  # type: ignore[no-untyped-def]
                if self.name == "project.health":
                    return ToolResult(ok=True, data="Project check — git: ok | analyze: ok")
                return ToolResult(ok=True, data=f"ok:{self.name}")

        for name in (
            "dev.run_tests",
            "dev.fix_cycle",
            "dev.analyze_repo",
            "git.status",
            "project.health",
        ):
            self.os.tools.register(_Ok(name, name, PermissionLevel.READ))

    def tearDown(self) -> None:
        self.os.close()
        self._tmp.cleanup()

    def _speech(self, command: str) -> str:
        turn = self.os.handle_turn(command)
        self.assertIsNotNone(turn.speech, command)
        self.assertFalse(turn.allow_cursor, command)
        return str(turn.speech)

    def test_analyze_project(self) -> None:
        speech = self._speech("Jarvis, projeyi analiz et.")
        self.assertIn("Project check", speech)

    def test_find_bug(self) -> None:
        self.assertTrue(self._speech("Jarvis, bu hatayı bul."))

    def test_fix_bug(self) -> None:
        self.assertTrue(self._speech("Jarvis, hatayı düzelt."))

    def test_run_tests(self) -> None:
        self.assertTrue(self._speech("Jarvis, testleri çalıştır."))

    def test_git_status(self) -> None:
        self.assertTrue(self._speech("Jarvis, Git durumunu kontrol et."))

    def test_continue_yesterday(self) -> None:
        self.os.tasks.create("Yesterday thread", description="pick up")
        speech = self._speech("Jarvis, dün yaptığımız işe devam et.")
        self.assertIn("Picking up", speech)

    def test_edit_file_asks_when_unknown(self) -> None:
        speech = self._speech("Jarvis, bu dosyayı düzenle.")
        self.assertIn("file", speech.lower())

    def test_edit_file_uses_last_path(self) -> None:
        (self.root / "note.txt").write_text("hello\n", encoding="utf-8")
        self.os.context.set_extra("last_file", "note.txt")
        speech = self._speech("Jarvis, bu dosyayı düzenle.")
        self.assertIn("note.txt", speech)

    def test_system_status(self) -> None:
        self.assertTrue(self._speech("Jarvis, sistem durumunu kontrol et."))

    def test_retry_last_failed(self) -> None:
        class Boom(StubTool):
            name = "test.boom_once"

            def run(self, arguments):  # type: ignore[no-untyped-def]
                return ToolResult(ok=False, error="simulated fail")

        self.os.tools.register(Boom("test.boom_once", "boom", PermissionLevel.READ))
        fail = self.os.execution.execute(ExecutionRequest("test.boom_once", {}))
        self.assertFalse(fail.ok)
        self.os._last_failed_request = ExecutionRequest("test.boom_once", {})
        self.assertTrue(self._speech("Jarvis, başarısız olan işlemi tekrar dene."))

    def test_stop(self) -> None:
        speech = self._speech("Jarvis, bu işi durdur.")
        self.assertIn("stop", speech.lower())

    def test_dual_locale_health_ok(self) -> None:
        health = self.os.health()
        lang = next(c for c in health["checks"] if c["name"] == "language")
        self.assertTrue(lang["ok"])
        self.assertTrue(lang["meta"].get("dual_locale"))


if __name__ == "__main__":
    unittest.main()
