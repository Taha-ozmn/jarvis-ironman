"""Live MCP JSON-RPC client over stdio (stdlib only — no mcp package required).

Implements a minimal subset: initialize, tools/list, tools/call.
Uses Content-Length framing (LSP/MCP style). Failures never raise into voice path.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from core.connection_recovery import connection_recovery, ConnectionType
from core.process_manager import ProcessConfig, ProcessType, process_manager

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=list)
    transport: str = "stdio"
    enabled: bool = True
    permission_level: int = 1  # LOCAL by default for remote tools

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPServerConfig":
        return cls(
            name=str(data.get("name") or "mcp").strip() or "mcp",
            command=str(data.get("command") or "").strip(),
            args=[str(a) for a in (data.get("args") or [])],
            env={str(k): str(v) for k, v in (data.get("env") or {}).items()},
            transport=str(data.get("transport") or "stdio").lower(),
            enabled=bool(data.get("enabled", True)),
            permission_level=int(data.get("permission_level", 1)),
        )


@dataclass
class RemoteToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]


class MCPClientError(Exception):
    pass


class StdioMCPClient:
    """One stdio MCP server session."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._proc: Optional[subprocess.Popen[str]] = None
        self._id = 0
        self._lock = threading.RLock()
        self._connected = False
        self._tools: list[RemoteToolInfo] = []
        self._last_error: str = ""
        self._connection_id = f"mcp_{config.name}"

    @property
    def connected(self) -> bool:
        return self._connected and self._proc is not None and self._proc.poll() is None

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def tools(self) -> list[RemoteToolInfo]:
        return list(self._tools)

    def connect(self, *, timeout: float = 15.0) -> bool:
        """Connect to the MCP server with connection recovery."""
        def _connect_operation():
            with self._lock:
                if self.connected:
                    return True
                if self.config.transport != "stdio":
                    self._last_error = f"Unsupported transport: {self.config.transport}"
                    return False
                if not self.config.command:
                    self._last_error = "No command configured"
                    return False
                try:
                    env = os.environ.copy()
                    env.update(self.config.env)
                    self._proc = subprocess.Popen(
                        [self.config.command, *self.config.args],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=0,
                        env=env,
                    )

                    # Register the process with the process manager for monitoring
                    from core.process_manager import ProcessConfig, ProcessType, ManagedProcess
                    proc_config = ProcessConfig(
                        process_type=ProcessType.MCP_SERVER,
                        name=self.config.name,
                        connection_type=ConnectionType.MCP_STDIO,
                        restart_on_failure=True,
                        max_restart_attempts=3,
                        cleanup_on_exit=True
                    )

                    proc_info = ManagedProcess(
                        pid=self._proc.pid,
                        config=proc_config,
                        proc=self._proc
                    )
                    process_manager._processes[self._proc.pid] = proc_info
                    # Add to process group
                    group_name = f"{proc_config.process_type.value}_{proc_config.name}"
                    if group_name not in process_manager._process_groups:
                        process_manager._process_groups[group_name] = set()
                    process_manager._process_groups[group_name].add(self._proc.pid)

                    self._initialize(timeout=timeout)
                    self._tools = self._list_tools(timeout=timeout)
                    self._connected = True
                    self._last_error = ""
                    return True
                except Exception as err:
                    self._last_error = str(err)
                    logger.exception("MCP connect failed for %s", self.config.name)
                    self.close()
                    return False

        try:
            result = connection_recovery.execute_with_recovery(
                self._connection_id,
                _connect_operation,
                connection_type=ConnectionType.MCP_STDIO,
                on_reconnect=self._on_reconnect,
                on_failure=self._on_connect_failure
            )
            return result
        except Exception as e:
            self._last_error = str(e)
            logger.exception("MCP connect failed after retries for %s", self.config.name)
            return False

    def call_tool(
        self,
        name: str,
        arguments: Optional[dict[str, Any]] = None,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Call a tool with connection recovery."""
        def _call_tool_operation():
            with self._lock:
                if not self.connected:
                    raise MCPClientError(self._last_error or "Not connected")
                result = self._request(
                    "tools/call",
                    {"name": name, "arguments": arguments or {}},
                    timeout=timeout,
                )
                return result if isinstance(result, dict) else {"content": result}

        try:
            return connection_recovery.execute_with_recovery(
                f"{self._connection_id}_call",
                _call_tool_operation,
                connection_type=ConnectionType.MCP_STDIO,
                on_failure=lambda e: None  # Handle failure in the operation itself
            )
        except Exception as e:
            self._last_error = str(e)
            raise MCPClientError(self._last_error) from e

    def close(self) -> None:
        """Close the MCP connection."""
        with self._lock:
            self._connected = False
            proc = self._proc
            proc_pid = self._proc_pid
            self._proc = None
            self._proc_pid = None
            if proc is None:
                return

            # Close streams
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass

            # Terminate the process
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

            # Remove from process manager
            from core.process_manager import process_manager
            if proc_pid is not None:
                process_manager.terminate_process(proc_pid, force=True)

    def _on_reconnect(self) -> None:
        """Handle successful reconnection."""
        logger.info("MCP client reconnected for %s", self.config.name)

    def _on_connect_failure(self, exception: Exception) -> None:
        """Handle connection failure."""
        logger.warning("MCP client connection failed for %s: %s", self.config.name, exception)

    def _initialize(self, *, timeout: float) -> None:
        """Initialize the MCP connection with recovery."""
        self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "jarvis-2", "version": "2.0"},
            },
            timeout=timeout,
        )
        self._notify("notifications/initialized", {})

    def _list_tools(self, *, timeout: float) -> list[RemoteToolInfo]:
        """List available tools with recovery."""
        result = self._request("tools/list", {}, timeout=timeout)
        items = (result or {}).get("tools") if isinstance(result, dict) else None
        out: list[RemoteToolInfo] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            schema = item.get("inputSchema") or item.get("input_schema") or {}
            if not isinstance(schema, dict):
                schema = {}
            out.append(
                RemoteToolInfo(
                    name=name,
                    description=str(item.get("description") or name),
                    input_schema=schema,
                )
            )
        return out

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a notification to the MCP server."""
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        self._write(msg)

    def _request(self, method: str, params: dict[str, Any], *, timeout: float) -> Any:
        """Make a request to the MCP server with connection recovery."""
        def _request_operation():
            req_id = self._next_id()
            msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            self._write(msg)
            deadline = timeout
            while deadline > 0:
                frame = self._read(timeout=min(2.0, deadline))
                deadline -= 2.0
                if frame is None:
                    continue
                if frame.get("id") != req_id:
                    # skip unrelated notifications
                    continue
                if "error" in frame:
                    err = frame["error"]
                    raise MCPClientError(str(err))
                return frame.get("result")
            raise MCPClientError(f"Timeout waiting for {method}")

        return connection_recovery.execute_with_recovery(
            f"{self._connection_id}_request",
            _request_operation,
            connection_type=ConnectionType.MCP_STDIO,
            on_failure=lambda e: None  # Handle in the operation
        )

    def _write(self, msg: dict[str, Any]) -> None:
        """Write a message to the MCP server process with recovery."""
        def _write_operation():
            if not self._proc or not self._proc.stdin:
                raise MCPClientError("Process stdin closed")
            body = json.dumps(msg, ensure_ascii=False)
            # Content-Length framing
            data = f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}"
            self._proc.stdin.write(data)
            self._proc.stdin.flush()

        # For write operations, we don't want to retry indefinitely as it might corrupt state
        # But we can retry a few times for transient issues
        connection_recovery.execute_with_recovery(
            f"{self._connection_id}_write",
            _write_operation,
            connection_type=ConnectionType.MCP_STDIO,
            on_failure=lambda e: None
        )

    def _read(self, *, timeout: float) -> Optional[dict[str, Any]]:
        """Read a message from the MCP server process with recovery."""
        def _read_operation():
            if not self._proc or not self._proc.stdout:
                raise MCPClientError("Process stdout closed")
            # Blocking read with a simple approach: read headers then body
            # Use a thread for timeout
            result: dict[str, Any] = {}
            error: list[BaseException] = []

            def _worker() -> None:
                try:
                    headers: dict[str, str] = {}
                    while True:
                        line = self._proc.stdout.readline()  # type: ignore[union-attr]
                        if line == "" and self._proc.poll() is not None:  # type: ignore[union-attr]
                            raise MCPClientError("MCP process exited")
                        if line in ("\r\n", "\n", ""):
                            if headers:
                                break
                            continue
                        if ":" in line:
                            k, v = line.split(":", 1)
                            headers[k.strip().lower()] = v.strip()
                    length = int(headers.get("content-length") or "0")
                    body = self._proc.stdout.read(length)  # type: ignore[union-attr]
                    result.update(json.loads(body))
                except BaseException as err:
                    error.append(err)

            t = threading.Thread(target=_worker, daemon=True)
            t.start()
            t.join(timeout=timeout)
            if t.is_alive():
                return None
            if error:
                raise error[0]
            return result or None

        return connection_recovery.execute_with_recovery(
            f"{self._connection_id}_read",
            _read_operation,
            connection_type=ConnectionType.MCP_STDIO,
            on_failure=lambda e: None
        )