"""Unit tests for tool registry."""

from __future__ import annotations

import unittest

from security.permissions import PermissionLevel
from tools.base import StubTool
from tools.registry import ToolRegistry, register_builtin_stubs


class ToolRegistryTests(unittest.TestCase):
    def test_register_and_discover(self) -> None:
        reg = ToolRegistry()
        reg.register(
            StubTool("demo", "demo tool", PermissionLevel.READ, {"q": {"type": "str", "required": True}})
        )
        self.assertIn("demo", reg.list_names())
        self.assertEqual(reg.get("demo").name, "demo")

    def test_validate_missing_required(self) -> None:
        reg = ToolRegistry()
        reg.register(
            StubTool(
                "demo",
                "demo",
                PermissionLevel.READ,
                {"q": {"type": "str", "required": True}},
            )
        )
        err = reg.validate_input("demo", {})
        self.assertIsNotNone(err)
        self.assertIn("q", err or "")

    def test_validate_type(self) -> None:
        reg = ToolRegistry()
        reg.register(
            StubTool(
                "demo",
                "demo",
                PermissionLevel.READ,
                {"n": {"type": "int", "required": True}},
            )
        )
        self.assertIsNotNone(reg.validate_input("demo", {"n": "x"}))
        self.assertIsNone(reg.validate_input("demo", {"n": 3}))

    def test_builtin_stubs(self) -> None:
        reg = ToolRegistry()
        register_builtin_stubs(reg)
        self.assertGreaterEqual(len(reg.list_names()), 5)
        tool = reg.get("browser.navigate")
        assert tool is not None
        result = tool.run({"url": "https://example.com"})
        self.assertFalse(result.ok)
        self.assertIn("stub", (result.error or "").lower())

    def test_discover_by_level(self) -> None:
        reg = ToolRegistry()
        register_builtin_stubs(reg)
        read_only = reg.discover(max_level=PermissionLevel.READ)
        self.assertTrue(all(s.permission_level <= PermissionLevel.READ for s in read_only))


if __name__ == "__main__":
    unittest.main()
