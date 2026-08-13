"""Live MCP client tests — fake stdio server, no real Cursor MCP required."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from core.app import JarvisOS
from integrations.mcp_adapter import MCPAdapter
from integrations.mcp_client import MCPServerConfig, StdioMCPClient
from tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parent.parent
FAKE = ROOT / "integrations" / "fake_mcp_server.py"


class LiveMCPClientTests(unittest.TestCase):
    def test_connect_list_and_call_fake_server(self) -> None:
        self.assertTrue(FAKE.exists(), "fake_mcp_server.py missing")
        cfg = MCPServerConfig(
            name="fake",
            command=sys.executable,
            args=[str(FAKE)],
            transport="stdio",
        )
        client = StdioMCPClient(cfg)
        try:
            self.assertTrue(client.connect(timeout=10), client.last_error)
            names = [t.name for t in client.tools]
            self.assertIn("echo", names)
            result = client.call_tool("echo", {"text": "hello"})
            text = ""
            for part in result.get("content") or []:
                if isinstance(part, dict):
                    text += str(part.get("text") or "")
            self.assertIn("echo:hello", text)
        finally:
            client.close()

    def test_adapter_registers_proxy_tools(self) -> None:
        registry = ToolRegistry()
        adapter = MCPAdapter()
        summary = adapter.connect_servers(
            [
                {
                    "name": "fake",
                    "command": sys.executable,
                    "args": [str(FAKE)],
                    "transport": "stdio",
                    "permission_level": 1,
                }
            ],
            registry,
        )
        try:
            self.assertEqual(summary["connected"], 1, summary)
            self.assertIn("mcp.fake.echo", registry.list_names())
            tool = registry.get("mcp.fake.echo")
            assert tool is not None
            result = tool.run({"text": "jarvis"})
            self.assertTrue(result.ok, result.error)
            self.assertIn("echo:jarvis", str(result.data))
            status = adapter.status()
            self.assertTrue(status["runtime"])
        finally:
            adapter.close_all()

    def test_no_servers_diagnostics_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {
                    "jarvis2": {
                        "db_path": "data/mcp.db",
                        "max_permission_level": 2,
                        "mcp": {"enabled": True, "servers": []},
                    }
                },
                root=Path(tmp),
            )
            try:
                health = os_core.health()
                mcp_check = next(c for c in health["checks"] if c["name"] == "mcp")
                self.assertTrue(mcp_check["ok"])
                self.assertIn("no MCP", mcp_check["detail"])
            finally:
                os_core.close()

    def test_bad_command_isolated(self) -> None:
        registry = ToolRegistry()
        adapter = MCPAdapter()
        summary = adapter.connect_servers(
            [
                {
                    "name": "broken",
                    "command": "/nonexistent/mcp-binary-xyz",
                    "args": [],
                }
            ],
            registry,
        )
        self.assertEqual(summary["connected"], 0)
        self.assertTrue(summary["errors"])
        # Registry should not have crashed
        self.assertEqual(registry.list_names(), [])
        adapter.close_all()


if __name__ == "__main__":
    unittest.main()
