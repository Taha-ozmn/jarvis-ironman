"""Calendar + GitHub routers/tools (mocked subprocess / REST)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core.command_router import CommandRouter
from tools.calendar_tools import (
    CalendarCreateEventTool,
    CalendarListTodayTool,
    parse_event_fields,
)
from tools.github_tools import (
    GithubCreateIssueTool,
    GithubListIssuesTool,
    GithubListPullsTool,
    MISSING_AUTH,
)


class CalendarRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_today_meetings(self) -> None:
        m = self.router.route("bugünkü toplantılar")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "calendar.list_today")

    def test_takvim_lists(self) -> None:
        m = self.router.route("takvim")
        self.assertEqual(m.request.tool_name, "calendar.list_today")

    def test_create_event(self) -> None:
        m = self.router.route("randevu ekle yarın 14:00 Demo")
        self.assertEqual(m.request.tool_name, "calendar.create_event")

    def test_takvim_ac_still_opens_app(self) -> None:
        m = self.router.route("takvim aç")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.request.tool_name, "system.open_app")


class CalendarToolTests(unittest.TestCase):
    def test_parse_event_fields(self) -> None:
        fields = parse_event_fields("randevu ekle yarın 14:00 Demo toplantısı")
        self.assertIn("Demo", fields["title"])
        self.assertEqual(fields["start"].hour, 14)

    def test_list_today_mocked(self) -> None:
        with patch(
            "tools.calendar_tools._osascript",
            return_value=(True, "Standup | Friday at 10:00\n"),
        ):
            result = CalendarListTodayTool().run({})
        self.assertTrue(result.ok)
        self.assertIn("Standup", result.data)

    def test_list_denied(self) -> None:
        with patch(
            "tools.calendar_tools._osascript",
            return_value=(False, "Not authorized to send Apple events to Calendar"),
        ):
            result = CalendarListTodayTool().run({})
        self.assertFalse(result.ok)
        self.assertIn("izni yok", result.error or "")

    def test_create_mocked(self) -> None:
        with patch(
            "tools.calendar_tools._osascript",
            return_value=(True, "ok"),
        ):
            result = CalendarCreateEventTool().run({"text": "randevu ekle 16:00 Review"})
        self.assertTrue(result.ok)
        self.assertIn("Review", result.data)


class GithubRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CommandRouter()

    def test_issues(self) -> None:
        m = self.router.route("github issue'larım")
        self.assertEqual(m.request.tool_name, "github.list_issues")

    def test_prs(self) -> None:
        m = self.router.route("PR'ları listele")
        self.assertEqual(m.request.tool_name, "github.list_pulls")

    def test_create_issue(self) -> None:
        m = self.router.route("issue aç login bug")
        self.assertEqual(m.request.tool_name, "github.create_issue")


class GithubToolTests(unittest.TestCase):
    def test_honest_without_auth(self) -> None:
        with patch("tools.github_tools._gh_bin", return_value=None), patch(
            "tools.github_tools._token", return_value=""
        ):
            issues = GithubListIssuesTool().run({})
            prs = GithubListPullsTool().run({})
            created = GithubCreateIssueTool().run({"title": "x"})
        self.assertFalse(issues.ok)
        self.assertIn("GITHUB_TOKEN", issues.error or "")
        self.assertIn("gh auth", issues.error or "")
        self.assertFalse(prs.ok)
        self.assertFalse(created.ok)
        self.assertIn("commit", MISSING_AUTH.lower())

    def test_list_issues_via_gh(self) -> None:
        with patch("tools.github_tools._gh_bin", return_value="/usr/bin/gh"), patch(
            "tools.github_tools._run_gh",
            return_value=(True, "#1 login bug"),
        ), patch("tools.github_tools.resolve_repo", return_value="o/r"):
            result = GithubListIssuesTool().run({})
        self.assertTrue(result.ok)
        self.assertIn("#1", result.data)

    def test_create_issue_rest(self) -> None:
        with patch("tools.github_tools._gh_bin", return_value=None), patch(
            "tools.github_tools._token", return_value="ghs_test"
        ), patch("tools.github_tools.resolve_repo", return_value="o/r"), patch(
            "tools.github_tools._rest",
            return_value=(True, {"number": 7, "html_url": "https://github.com/o/r/issues/7"}, ""),
        ):
            result = GithubCreateIssueTool().run({"title": "bug"})
        self.assertTrue(result.ok)
        self.assertIn("#7", result.data)


if __name__ == "__main__":
    unittest.main()
