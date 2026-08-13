"""Thin MCP adapter + live stdio client wiring into ToolRegistry."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from integrations.mcp_client import MCPServerConfig, StdioMCPClient
from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class MCPToolSchema:
    """MCP-like tool descriptor (JSON-serializable)."""

    name: str
    description: str
    input_schema: dict[str, Any]
    permission_level: int = 0


@dataclass
class MCPServerRegistration:
    name: str
    tools: list[MCPToolSchema] = field(default_factory=list)
    transport: str = "stdio"
    connected: bool = False
    error: str = ""
    client: Optional[StdioMCPClient] = None


class MCPRemoteTool(BaseTool):
    """Proxy a remote MCP tool into the local registry."""

    def __init__(
        self,
        *,
        local_name: str,
        remote_name: str,
        description: str,
        input_schema: dict[str, Any],
        permission_level: PermissionLevel,
        client: StdioMCPClient,
    ) -> None:
        self.name = local_name
        self.description = description
        self.permission_level = permission_level
        self.input_schema = _jsonschema_to_jarvis(input_schema)
        self._remote_name = remote_name
        self._client = client

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            result = self._client.call_tool(self._remote_name, arguments or {})
        except Exception as err:
            return ToolResult(ok=False, error=f"MCP call failed: {err}")
        # MCP tools/call result shape: {content:[{type,text}], isError?}
        if isinstance(result, dict) and result.get("isError"):
            text = _extract_text(result) or "remote tool error"
            return ToolResult(ok=False, error=text)
        text = _extract_text(result) if isinstance(result, dict) else str(result)
        return ToolResult(ok=True, data=text or "OK")


class MCPAdapter:
    """Bridge internal tools ↔ MCP schema and manage live stdio sessions."""

    def __init__(self) -> None:
        self._servers: dict[str, MCPServerRegistration] = {}

    def tool_to_schema(self, tool: BaseTool) -> MCPToolSchema:
        props: dict[str, Any] = {}
        required: list[str] = []
        for key, rules in (tool.input_schema or {}).items():
            props[key] = {"type": rules.get("type", "string")}
            if rules.get("required"):
                required.append(key)
        return MCPToolSchema(
            name=tool.name,
            description=tool.description or "",
            input_schema={
                "type": "object",
                "properties": props,
                "required": required,
            },
            permission_level=int(tool.permission_level),
        )

    def export_registry(self, registry: ToolRegistry) -> list[MCPToolSchema]:
        return [
            self.tool_to_schema(registry.get(n))
            for n in registry.list_names()
            if registry.get(n)
        ]

    def register_server(
        self,
        name: str,
        *,
        tools: Optional[list[MCPToolSchema]] = None,
        transport: str = "stdio",
        connected: bool = False,
        error: str = "",
        client: Optional[StdioMCPClient] = None,
    ) -> MCPServerRegistration:
        reg = MCPServerRegistration(
            name=name,
            tools=list(tools or []),
            transport=transport,
            connected=connected,
            error=error,
            client=client,
        )
        self._servers[name] = reg
        return reg

    def connect_servers(
        self,
        configs: list[dict[str, Any]] | list[MCPServerConfig],
        registry: ToolRegistry,
    ) -> dict[str, Any]:
        """Connect configured MCP servers and register proxy tools. Isolated failures."""
        summary = {"attempted": 0, "connected": 0, "tools": 0, "errors": []}
        for raw in configs or []:
            cfg = raw if isinstance(raw, MCPServerConfig) else MCPServerConfig.from_dict(raw)
            if not cfg.enabled:
                continue
            summary["attempted"] += 1
            client = StdioMCPClient(cfg)
            ok = False
            try:
                ok = client.connect()
            except Exception as err:
                logger.exception("MCP connect crashed: %s", cfg.name)
                self.register_server(
                    cfg.name,
                    transport=cfg.transport,
                    connected=False,
                    error=str(err),
                    client=None,
                )
                summary["errors"].append(f"{cfg.name}: {err}")
                continue
            if not ok:
                self.register_server(
                    cfg.name,
                    transport=cfg.transport,
                    connected=False,
                    error=client.last_error,
                    client=None,
                )
                summary["errors"].append(f"{cfg.name}: {client.last_error}")
                try:
                    client.close()
                except Exception:
                    pass
                continue

            schemas: list[MCPToolSchema] = []
            level = PermissionLevel(max(0, min(3, cfg.permission_level)))
            for tool in client.tools:
                local_name = f"mcp.{cfg.name}.{tool.name}"
                proxy = MCPRemoteTool(
                    local_name=local_name,
                    remote_name=tool.name,
                    description=f"[MCP:{cfg.name}] {tool.description}",
                    input_schema=tool.input_schema,
                    permission_level=level,
                    client=client,
                )
                registry.register(proxy)
                schemas.append(
                    MCPToolSchema(
                        name=local_name,
                        description=proxy.description,
                        input_schema=tool.input_schema,
                        permission_level=int(level),
                    )
                )
                summary["tools"] += 1
            self.register_server(
                cfg.name,
                tools=schemas,
                transport=cfg.transport,
                connected=True,
                client=client,
            )
            summary["connected"] += 1
        return summary

    def close_all(self) -> None:
        for reg in list(self._servers.values()):
            if reg.client is not None:
                try:
                    reg.client.close()
                except Exception:
                    logger.exception("MCP close failed: %s", reg.name)
                reg.connected = False

    def list_servers(self) -> list[dict[str, Any]]:
        return [
            {
                "name": s.name,
                "transport": s.transport,
                "connected": s.connected,
                "tools": len(s.tools),
                "error": s.error or None,
                "note": (
                    "connected"
                    if s.connected
                    else (s.error or "not connected / no servers configured")
                ),
            }
            for s in self._servers.values()
        ]

    def example_mapping(self) -> dict[str, Any]:
        return {
            "internal": "memory.search",
            "mcp": {
                "name": "memory.search",
                "description": "Search long-term memories",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            "status": "live stdio client available when jarvis2.mcp.servers configured",
        }

    def status(self) -> dict[str, Any]:
        connected = sum(1 for s in self._servers.values() if s.connected)
        return {
            "runtime": connected > 0,
            "connected": connected,
            "configured": len(self._servers),
            "servers": self.list_servers(),
            "example": self.example_mapping(),
        }


def _jsonschema_to_jarvis(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert MCP JSON Schema properties to jarvis input_schema."""
    props = schema.get("properties") if isinstance(schema, dict) else None
    required = set(schema.get("required") or []) if isinstance(schema, dict) else set()
    out: dict[str, Any] = {}
    if not isinstance(props, dict):
        return out
    for key, meta in props.items():
        typ = "str"
        if isinstance(meta, dict):
            t = str(meta.get("type") or "string").lower()
            if t in ("integer", "int", "number"):
                typ = "int" if t != "number" else "float"
            elif t == "boolean":
                typ = "bool"
            elif t == "string":
                typ = "str"
        out[key] = {"type": typ, "required": key in required}
    return out


def _extract_text(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
        return " ".join(p for p in parts if p).strip()
    if "text" in result:
        return str(result["text"])
    return str(result)[:400]
