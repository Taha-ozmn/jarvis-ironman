"""Process management system for JARVIS 2.0.

Provides centralized process spawning, monitoring, and cleanup functionality
for managing subprocess operations throughout the application.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from contextlib import contextmanager

from core.timeout_manager import timeout_manager, TimeoutType
from core.connection_recovery import connection_recovery, ConnectionType


class ProcessType(Enum):
    """Types of processes that can be managed."""
    MCP_SERVER = "mcp_server"
    BROWSER_AUTOMATION = "browser_automation"
    SYSTEM_TOOL = "system_tool"
    BACKGROUND_SERVICE = "background_service"
    RESTART_HANDLER = "restart_handler"


@dataclass
class ProcessConfig:
    """Configuration for a managed process."""
    process_type: ProcessType
    name: str
    timeout_type: TimeoutType = TimeoutType.TERMINAL
    connection_type: Optional[ConnectionType] = None
    restart_on_failure: bool = False
    max_restart_attempts: int = 3
    restart_delay: float = 5.0
    cleanup_on_exit: bool = True
    resource_limits: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ManagedProcess:
    """Tracks a managed process."""
    pid: int
    config: ProcessConfig
    proc: subprocess.Popen
    created_at: float = field(default_factory=time.time)
    last_health_check: float = field(default_factory=time.time)
    restart_count: int = 0
    is_healthy: bool = True
    stdout_data: List[bytes] = field(default_factory=list)
    stderr_data: List[bytes] = field(default_factory=list)

    @property
    def is_running(self) -> bool:
        """Check if the process is still running."""
        return self.proc.poll() is None

    @property
    def age(self) -> float:
        """Get the age of the process in seconds."""
        return time.time() - self.created_at


class ProcessManager:
    """Manages processes for JARVIS 2.0."""

    def __init__(self):
        self._processes: Dict[int, ManagedProcess] = {}
        self._process_groups: Dict[str, Set[int]] = {}
        self._lock = threading.RLock()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._start_cleanup_thread()

    def _start_cleanup_thread(self):
        """Start the background cleanup thread."""
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_worker,
            daemon=True,
            name="JARVIS-ProcessCleanup"
        )
        self._cleanup_thread.start()

    def _cleanup_worker(self):
        """Background worker to monitor and cleanup processes."""
        while not self._shutdown_event.wait(5.0):  # Check every 5 seconds
            try:
                self._monitor_processes()
                self._cleanup_terminated_processes()
            except Exception as e:
                # Log but don't break the cleanup thread
                print(f"⚠️  Process manager cleanup error: {e}")

    def _monitor_processes(self):
        """Monitor health of managed processes."""
        with self._lock:
            for proc_info in list(self._processes.values()):
                try:
                    self._check_process_health(proc_info)
                except Exception:
                    pass  # Continue monitoring other processes

    def _check_process_health(self, proc_info: ManagedProcess):
        """Check health of a specific process."""
        # Update last health check time
        proc_info.last_health_check = time.time()

        # Check if process is still running
        if not proc_info.is_running:
            proc_info.is_healthy = False

            # Attempt restart if configured
            if (proc_info.config.restart_on_failure and
                proc_info.restart_count < proc_info.config.max_restart_attempts):
                self._restart_process(proc_info)
            return

        # Process is running, mark as healthy
        proc_info.is_healthy = True

        # Collect output if needed (non-blocking)
        try:
            if proc_info.proc.stdout:
                # Read available output without blocking
                import select
                if hasattr(select, 'select'):
                    ready, _, _ = select.select([proc_info.proc.stdout], [], [], 0)
                    if ready:
                        data = proc_info.proc.stdout.read(1024)
                        if data:
                            proc_info.stdout_data.append(data)
                            # Keep only last 10 chunks to prevent memory growth
                            if len(proc_info.stdout_data) > 10:
                                proc_info.stdout_data = proc_info.stdout_data[-10:]
        except Exception:
            pass  # Ignore output collection errors

        try:
            if proc_info.proc.stderr:
                import select
                if hasattr(select, 'select'):
                    ready, _, _ = select.select([proc_info.proc.stderr], [], [], 0)
                    if ready:
                        data = proc_info.proc.stderr.read(1024)
                        if data:
                            proc_info.stderr_data.append(data)
                            if len(proc_info.stderr_data) > 10:
                                proc_info.stderr_data = proc_info.stderr_data[-10:]
        except Exception:
            pass

    def _restart_process(self, proc_info: ManagedProcess):
        """Restart a failed process."""
        try:
            print(f"🔄 Restarting process {proc_info.config.name} (PID: {proc_info.pid})")

            # Terminate the old process
            self._terminate_process_inner(proc_info.proc, force=False)

            # Wait a bit before restarting
            time.sleep(proc_info.config.restart_delay)

            # Spawn new process with same config
            new_proc = self._spawn_process_inner(proc_info.config)

            # Replace the old process info
            with self._lock:
                old_pid = proc_info.pid
                proc_info.pid = new_proc.pid
                proc_info.proc = new_proc
                proc_info.created_at = time.time()
                proc_info.last_health_check = time.time()
                proc_info.restart_count += 1
                proc_info.is_healthy = True
                proc_info.stdout_data.clear()
                proc_info.stderr_data.clear()

                # Update process mapping
                if old_pid in self._processes:
                    del self._processes[old_pid]
                self._processes[proc_info.pid] = proc_info

                # Update process groups
                for group_name, pids in self._process_groups.items():
                    if old_pid in pids:
                        pids.discard(old_pid)
                        pids.add(proc_info.pid)

            print(f"✅ Restarted process {proc_info.config.name} (New PID: {proc_info.pid})")

        except Exception as e:
            print(f"❌ Failed to restart process {proc_info.config.name}: {e}")
            proc_info.is_healthy = False

    def _cleanup_terminated_processes(self):
        """Remove terminated processes from tracking."""
        with self._lock:
            terminated_pids = []
            for pid, proc_info in self._processes.items():
                if not proc_info.is_running:
                    terminated_pids.append(pid)

            for pid in terminated_pids:
                proc_info = self._processes.pop(pid, None)
                if proc_info:
                    # Remove from process groups
                    for group_name, pids in self._process_groups.items():
                        pids.discard(pid)

                    print(f"🧹 Cleaned up terminated process {proc_info.config.name} (PID: {pid})")

    def spawn_process(
        self,
        cmd: List[str],
        config: ProcessConfig,
        *,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        stdin: Any = None,
        stdout: Any = None,
        stderr: Any = None,
        connection_id: Optional[str] = None
    ) -> int:
        """Spawn a new managed process.

        Args:
            cmd: Command and arguments to execute
            config: Process configuration
            cwd: Working directory
            env: Environment variables
            stdin: stdin handle
            stdout: stdout handle
            stderr: stderr handle
            connection_id: Optional connection ID for recovery integration

        Returns:
            PID of the spawned process
        """
        with self._lock:
            # Spawn the process
            proc = self._spawn_process_inner(config, cmd, cwd, env, stdin, stdout, stderr)

            # Create managed process info
            proc_info = ManagedProcess(
                pid=proc.pid,
                config=config,
                proc=proc
            )

            # Store it
            self._processes[proc.pid] = proc_info

            # Add to process group if named
            if config.name:
                group_name = f"{config.process_type.value}_{config.name}"
                if group_name not in self._process_groups:
                    self._process_groups[group_name] = set()
                self._process_groups[group_name].add(proc.pid)

            # Set up connection recovery integration if specified
            if connection_id and config.connection_type:
                connection_recovery.set_connection_type(connection_id, config.connection_type)

            print(f"🚀 Spawned process {config.name} (PID: {proc.pid}, Type: {config.process_type.value})")
            return proc.pid

    def _spawn_process_inner(
        self,
        config: ProcessConfig,
        cmd: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        stdin: Any = None,
        stdout: Any = None,
        stderr: Any = None
    ) -> subprocess.Popen:
        """Inner method to spawn a process with timeout context."""
        if cmd is None:
            cmd = config.name.split() if isinstance(config.name, str) else ["echo", "no-command"]

        # Prepare environment
        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)

        # Prepare startup info for hiding windows on Windows
        startupinfo = None
        creationflags = 0
        if os.name == 'nt':  # Windows
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW

        # Use timeout context for process spawning
        timeout = timeout_manager.get_timeout(config.timeout_type)

        def _spawn():
            return subprocess.Popen(
                cmd,
                cwd=cwd,
                env=proc_env,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                startupinfo=startupinfo,
                creationflags=creationflags,
                text=False,  # Keep as bytes for better control
                bufsize=0
            )

        # Execute with timeout protection
        try:
            with timeout_manager.timeout_context(TimeoutType.TERMINAL, timeout):
                return _spawn()
        except TimeoutError:
            raise RuntimeError(f"Failed to spawn process {' '.join(cmd)}: Timed out after {timeout}s")
        except Exception as e:
            raise RuntimeError(f"Failed to spawn process {' '.join(cmd)}: {e}")

    def terminate_process(self, pid: int, force: bool = False, timeout: float = 5.0) -> bool:
        """Terminate a managed process.

        Args:
            pid: Process ID to terminate
            force: Whether to force kill after graceful termination fails
            timeout: Seconds to wait for graceful termination

        Returns:
            True if process was terminated, False if not found
        """
        with self._lock:
            proc_info = self._processes.get(pid)
            if not proc_info:
                return False

            return self._terminate_process_inner(proc_info.proc, force, timeout)

    def _terminate_process_inner(
        self,
        proc: subprocess.Popen,
        force: bool = False,
        timeout: float = 5.0
    ) -> bool:
        """Inner method to terminate a process."""
        if proc.poll() is not None:
            return True  # Already terminated

        try:
            # Try graceful termination first
            proc.terminate()

            # Wait for graceful termination
            try:
                proc.wait(timeout=timeout)
                return True
            except subprocess.TimeoutExpired:
                if not force:
                    return False  # Timed out, not forced

                # Force kill
                proc.kill()
                proc.wait(timeout=2.0)  # Short wait for kill
                return True

        except Exception:
            # Process might already be gone
            return proc.poll() is not None

    def terminate_process_group(self, group_name: str, force: bool = False) -> int:
        """Terminate all processes in a group.

        Args:
            group_name: Name of the process group
            force: Whether to force kill processes

        Returns:
            Number of processes terminated
        """
        with self._lock:
            pids = self._process_groups.get(group_name, set()).copy()
            terminated_count = 0

            for pid in pids:
                if self.terminate_process(pid, force=force):
                    terminated_count += 1

            return terminated_count

    def terminate_all(self, force: bool = False):
        """Terminate all managed processes."""
        with self._lock:
            pids = list(self._processes.keys())
            for pid in pids:
                self.terminate_process(pid, force=force)

    def get_process_info(self, pid: int) -> Optional[ManagedProcess]:
        """Get information about a managed process.

        Args:
            pid: Process ID

        Returns:
            ManagedProcess info or None if not found
        """
        with self._lock:
            return self._processes.get(pid)

    def list_processes(self, process_type: Optional[ProcessType] = None) -> List[ManagedProcess]:
        """List all managed processes.

        Args:
            process_type: Optional filter by process type

        Returns:
            List of managed processes
        """
        with self._lock:
            processes = list(self._processes.values())
            if process_type:
                processes = [p for p in processes if p.config.process_type == process_type]
            return processes

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about managed processes.

        Returns:
            Dictionary with process statistics
        """
        with self._lock:
            total = len(self._processes)
            running = sum(1 for p in self._processes.values() if p.is_running)
            healthy = sum(1 for p in self._processes.values() if p.is_healthy)

            by_type = {}
            for proc_info in self._processes.values():
                ptype = proc_info.config.process_type.value
                if ptype not in by_type:
                    by_type[ptype] = {"total": 0, "running": 0, "healthy": 0}
                by_type[ptype]["total"] += 1
                if proc_info.is_running:
                    by_type[ptype]["running"] += 1
                if proc_info.is_healthy:
                    by_type[ptype]["healthy"] += 1

            return {
                "total_processes": total,
                "running_processes": running,
                "healthy_processes": healthy,
                "processes_by_type": by_type,
                "process_groups": {
                    name: len(pids)
                    for name, pids in self._process_groups.items()
                }
            }

    def is_process_healthy(self, pid: int) -> bool:
        """Check if a process is healthy.

        Args:
            pid: Process ID

        Returns:
            True if process is healthy, False otherwise
        """
        proc_info = self.get_process_info(pid)
        return proc_info.is_healthy if proc_info else False

    def wait_for_process(self, pid: int, timeout: Optional[float] = None) -> int:
        """Wait for a process to terminate.

        Args:
            pid: Process ID to wait for
            timeout: Optional timeout in seconds

        Returns:
            Exit code of the process

        Raises:
            TimeoutError: If timeout is exceeded
            ValueError: If process not found
        """
        proc_info = self.get_process_info(pid)
        if not proc_info:
            raise ValueError(f"Process {pid} not found")

        try:
            return proc_info.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"Wait for process {pid} timed out after {timeout}s")

    def shutdown(self):
        """Shutdown the process manager and cleanup all processes."""
        print("🛑 Shutting down process manager...")
        self._shutdown_event.set()

        # Wait for cleanup thread to finish
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=2.0)

        # Terminate all processes
        self.terminate_all(force=True)

        print("✅ Process manager shutdown complete")


# Global process manager instance
process_manager = ProcessManager()


@contextmanager
def managed_process(
    cmd: List[str],
    config: ProcessConfig,
    *,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
    connection_id: Optional[str] = None
):
    """Context manager for managing a process lifecycle.

    Example:
        with managed_process(["ls", "-la"], ProcessConfig(
            process_type=ProcessType.SYSTEM_TOOL,
            name="ls-listing"
        )) as pid:
            # Process is running
            info = process_manager.get_process_info(pid)
    """
    pid = process_manager.spawn_process(
        cmd, config,
        cwd=cwd, env=env,
        stdin=stdin, stdout=stdout, stderr=stderr,
        connection_id=connection_id
    )
    try:
        yield pid
    finally:
        process_manager.terminate_process(pid, force=True)


def with_process_management(
    process_type: ProcessType,
    name: str,
    *,
    restart_on_failure: bool = False,
    max_restart_attempts: int = 3
):
    """Decorator to add process management to a function that returns a command to run.

    The decorated function should return a tuple of (cmd, kwargs) where:
    - cmd: List[str] command to execute
    - kwargs: Dict of additional arguments for spawn_process

    Example:
        @with_process_management(ProcessType.MCP_SERVER, "my-mcp-server")
        def get_mcp_command():
            return (["mcp-server", "--port", "8080"], {"cwd": "/path/to/server"})
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            # Get command and spawn options from the decorated function
            result = func(*args, **kwargs)
            if isinstance(result, tuple) and len(result) == 2:
                cmd, spawn_kwargs = result
            else:
                # Assume the function returns just the command
                cmd = result if isinstance(result, list) else [str(result)]
                spawn_kwargs = {}

            # Create process config
            config = ProcessConfig(
                process_type=process_type,
                name=name,
                restart_on_failure=restart_on_failure,
                max_restart_attempts=max_restart_attempts
            )

            # Merge spawn options
            spawn_kwargs.update({
                "cwd": spawn_kwargs.get("cwd"),
                "env": spawn_kwargs.get("env"),
                "stdin": spawn_kwargs.get("stdin"),
                "stdout": spawn_kwargs.get("stdout"),
                "stderr": spawn_kwargs.get("stderr")
            })

            # Remove None values
            spawn_kwargs = {k: v for k, v in spawn_kwargs.items() if v is not None}

            # Spawn and manage the process
            pid = process_manager.spawn_process(cmd, config, **spawn_kwargs)
            try:
                yield pid  # This makes it a context manager decorator
            finally:
                process_manager.terminate_process(pid, force=True)

        # Make it usable as a context manager decorator
        return wrapper
    return decorator


# Convenience functions for common process types
def spawn_mcp_server(
    command: List[str],
    name: str,
    *,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    connection_id: Optional[str] = None
) -> int:
    """Spawn an MCP server process with standard configuration."""
    config = ProcessConfig(
        process_type=ProcessType.MCP_SERVER,
        name=name,
        connection_type=ConnectionType.MCP_STDIO,
        restart_on_failure=True,
        max_restart_attempts=3,
        cleanup_on_exit=True
    )

    return process_manager.spawn_process(
        command, config,
        cwd=cwd, env=env,
        connection_id=connection_id
    )


def spawn_browser_automation(
    command: List[str],
    name: str,
    *,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None
) -> int:
    """Spawn a browser automation process with standard configuration."""
    config = ProcessConfig(
        process_type=ProcessType.BROWSER_AUTOMATION,
        name=name,
        connection_type=ConnectionType.PLAYWRIGHT_BROWSER,
        timeout_type=TimeoutType.BROWSER,
        restart_on_failure=True,
        max_restart_attempts=2,
        cleanup_on_exit=True
    )

    return process_manager.spawn_process(
        command, config,
        cwd=cwd, env=env
    )


def spawn_system_tool(
    command: List[str],
    name: str,
    *,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    timeout_seconds: Optional[float] = None
) -> int:
    """Spawn a system tool process with standard configuration."""
    config = ProcessConfig(
        process_type=ProcessType.SYSTEM_TOOL,
        name=name,
        timeout_type=TimeoutType.TERMINAL,
        restart_on_failure=False,
        cleanup_on_exit=True
    )

    return process_manager.spawn_process(
        command, config,
        cwd=cwd, env=env
    )