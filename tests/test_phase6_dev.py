"""Phase 6 — developer analyze_repo tool."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.dev_tools import AnalyzeRepoTool


class DevAnalyzeTests(unittest.TestCase):
    def test_analyze_repo_lists_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# hi\n", encoding="utf-8")
            (root / "main.py").write_text("print('x')\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("x=1\n", encoding="utf-8")
            tool = AnalyzeRepoTool(lambda: root)
            result = tool.run({})
            self.assertTrue(result.ok, result.error)
            text = str(result.data)
            self.assertIn("README.md", text)
            self.assertIn("main.py", text)


if __name__ == "__main__":
    unittest.main()
