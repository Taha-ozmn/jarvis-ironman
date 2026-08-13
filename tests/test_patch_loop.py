"""LLM-assisted patch loop tests — mocked LLM, no silent writes."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.patch_tools import ApplyPatchTool, parse_patch_json


class FakeLLM:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def available(self) -> bool:
        return True

    def complete(self, prompt: str, *, category: str = "chat", timeout: float = 20.0) -> str:
        _ = (prompt, category, timeout)
        return self.payload


class PatchLoopTests(unittest.TestCase):
    def test_parse_patch_json(self) -> None:
        raw = '{"path":"hello.py","content":"print(1)\\n","rationale":"demo"}'
        patch = parse_patch_json(raw)
        assert patch is not None
        self.assertEqual(patch["path"], "hello.py")
        self.assertIn("print", patch["content"])

    def test_reject_path_traversal(self) -> None:
        self.assertIsNone(parse_patch_json('{"path":"../etc/passwd","content":"x"}'))

    def test_explicit_patch_write_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_ok.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            tool = ApplyPatchTool(lambda: root, llm=None)
            result = tool.run(
                {
                    "path": "hello.py",
                    "content": "print('hi')\n",
                    "goal": "add hello",
                }
            )
            self.assertTrue(result.ok, result.error)
            self.assertTrue((root / "hello.py").exists())

    def test_llm_propose_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text("x=1\n", encoding="utf-8")
            llm = FakeLLM(
                '{"path":"main.py","content":"x=2\\n","rationale":"bump"}'
            )
            tool = ApplyPatchTool(lambda: root, llm=llm)
            result = tool.run({"goal": "bump x", "dry_run": True})
            self.assertTrue(result.ok, result.error)
            self.assertIn("Dry-run", str(result.data))
            # file unchanged
            self.assertEqual((root / "main.py").read_text(encoding="utf-8"), "x=1\n")

    def test_no_llm_no_explicit_fails_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool = ApplyPatchTool(lambda: root, llm=None)
            result = tool.run({"goal": "fix something"})
            self.assertFalse(result.ok)
            self.assertIn("LLM unavailable", result.error or "")


if __name__ == "__main__":
    unittest.main()
