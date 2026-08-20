"""Phase 6 — research extractive path + screen tools (mocked)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.browser_tools import BrowserFillFormTool, browser_diagnostics
from tools.research_tools import ResearchTopicTool, extractive_summary
from tools.screen_tools import ScreenCaptureTool, ScreenDescribeTool


class ResearchTests(unittest.TestCase):
    def test_extractive_summary(self) -> None:
        summary = extractive_summary(
            "Python",
            ["Python is a programming language.", "It is widely used."],
        )
        self.assertIn("Python", summary)
        self.assertIn("programming", summary)

    def test_research_topic_with_mocked_snippets(self) -> None:
        tool = ResearchTopicTool(memory=None)
        with patch(
            "tools.research_tools.collect_research_snippets",
            return_value=["Snippet A about topic.", "Snippet B more detail."],
        ):
            result = tool.run({"query": "topic"})
        self.assertTrue(result.ok, result.error)
        self.assertIn("topic", str(result.data).lower())

    def test_research_empty_snippets(self) -> None:
        tool = ResearchTopicTool()
        with patch("tools.research_tools.collect_research_snippets", return_value=[]):
            result = tool.run({"query": "nothing"})
        self.assertFalse(result.ok)

    def test_research_optional_memory_save(self) -> None:
        memory = MagicMock()
        tool = ResearchTopicTool(memory=memory)
        with patch(
            "tools.research_tools.collect_research_snippets",
            return_value=["A useful fact about X."],
        ):
            result = tool.run({"query": "X", "save_memory": True})
        self.assertTrue(result.ok)
        memory.create.assert_called_once()


class BrowserHonestyTests(unittest.TestCase):
    def test_fill_form_not_implemented(self) -> None:
        result = BrowserFillFormTool().run({"url": "https://example.com"})
        self.assertFalse(result.ok)
        err = (result.error or "").lower()
        self.assertTrue(
            "playwright" in err or "not implemented" in err,
            result.error,
        )

    def test_browser_diagnostics(self) -> None:
        info = browser_diagnostics()
        self.assertIn("playwright", info)
        self.assertIn("engine", info)
        self.assertIn("note", info)
        self.assertIn("chromium", info)
        if info["playwright"] and info.get("chromium"):
            self.assertIn("playwright", str(info["engine"]))
        elif info["playwright"]:
            self.assertFalse(info.get("chromium"))
        else:
            self.assertEqual(info["engine"], "urllib+open")
            self.assertFalse(info.get("chromium"))


class ScreenToolsTests(unittest.TestCase):
    def test_capture_success_mocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "shot.png"
            out.write_bytes(b"PNG")  # pretouch; tool checks exists after run

            def fake_run(cmd, **kwargs):
                Path(cmd[2]).write_bytes(b"fake-png")
                return MagicMock(returncode=0, stdout="", stderr="")

            with patch("tools.vision.subprocess.run", side_effect=fake_run):
                result = ScreenCaptureTool().run({"path": str(out)})
            self.assertTrue(result.ok, result.error)
            self.assertIn(str(out), str(result.data))

    def test_capture_missing_binary(self) -> None:
        with patch(
            "tools.vision.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            result = ScreenCaptureTool().run({})
        self.assertFalse(result.ok)
        self.assertIn("screencapture", (result.error or "").lower())

    def test_describe_frontmost_mocked(self) -> None:
        with patch(
            "tools.screen_tools.capture_screen",
            return_value=(False, "no capture"),
        ), patch(
            "tools.screen_tools.frontmost_app_info",
            return_value={"name": "Cursor", "bundle": "com.todesktop.cursor", "title": "main"},
        ):
            result = ScreenDescribeTool().run({})
        self.assertTrue(result.ok)
        self.assertIn("Cursor", str(result.data))
        # Capture failed → still reports frontmost honestly (TR)
        self.assertTrue(
            "Cursor" in str(result.data)
            and (
                "ön planda" in str(result.data).lower()
                or "capture" in str(result.data).lower()
                or "açık" in str(result.data).lower()
            )
        )

    def test_describe_failure(self) -> None:
        with patch(
            "tools.screen_tools.capture_screen",
            return_value=(False, "screencapture failed"),
        ), patch("tools.screen_tools.frontmost_app_info", return_value=None):
            result = ScreenDescribeTool().run({})
        self.assertFalse(result.ok)


class CollectResearchPathTests(unittest.TestCase):
    def test_collect_uses_ddg_json(self) -> None:
        payload = {
            "AbstractText": "JARVIS is a fictional AI.",
            "RelatedTopics": [{"Text": "Related iron man note."}],
        }

        class FakeResp:
            def read(self):
                return json.dumps(payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("tools.research_tools.urllib.request.urlopen", return_value=FakeResp()):
            from tools.research_tools import collect_research_snippets

            snippets = collect_research_snippets("JARVIS")
        self.assertTrue(any("fictional" in s.lower() for s in snippets))


if __name__ == "__main__":
    unittest.main()
