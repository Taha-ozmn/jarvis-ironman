"""Thread-safe timeout_context + mail/Gmail routing."""

from __future__ import annotations

import threading
import unittest

from core.command_router import CommandRouter
from core.open_target import extract_site_url
from core.timeout_manager import TimeoutType, timeout_manager


class TimeoutThreadSafetyTests(unittest.TestCase):
    def test_timeout_context_works_off_main_thread(self) -> None:
        errors: list[BaseException] = []
        done = threading.Event()

        def worker() -> None:
            try:
                with timeout_manager.timeout_context(TimeoutType.BROWSER, 2.0):
                    pass
            except BaseException as err:  # noqa: BLE001 — capture for assert
                errors.append(err)
            finally:
                done.set()

        t = threading.Thread(target=worker)
        t.start()
        self.assertTrue(done.wait(5.0))
        t.join(timeout=1.0)
        self.assertEqual(errors, [])


class GmailOutlookRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_google_mail_account_opens_gmail(self) -> None:
        m = self.router.route("Google'dan mail hesabım aç")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "browser.open_url")
        self.assertIn("mail.google.com", m.request.arguments["url"])

    def test_gmail_open(self) -> None:
        m = self.router.route("gmail aç")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "browser.open_url")

    def test_outlook_phrase(self) -> None:
        m = self.router.route("Google'a Outlook yaz")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertIn(
            m.request.tool_name,
            {"browser.open_url", "system.open_app"},
        )

    def test_extract_gmail_url(self) -> None:
        self.assertIn("mail.google.com", extract_site_url("mail hesabımı aç") or "")


if __name__ == "__main__":
    unittest.main()
