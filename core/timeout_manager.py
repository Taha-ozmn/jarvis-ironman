"""Timeout management system for JARVIS 2.0.

Provides standardized timeout values and timeout contexts for different
operation types to prevent hanging operations and ensure proper resource cleanup.

IMPORTANT: signal.SIGALRM only works on the main thread. Voice commands run on
worker threads, so timeout_context must degrade gracefully off the main thread
(subprocess.run already has its own timeout= parameter).
"""

from __future__ import annotations

import enum
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional, Callable, Any, Iterator


class TimeoutType(enum.Enum):
    """Types of operations that have standardized timeouts."""
    AI_REQUEST = "ai_request"
    STT = "stt"
    TTS = "tts"
    BROWSER = "browser"
    TERMINAL = "terminal"
    FILE_OPERATION = "file_operation"
    NETWORK = "network"
    DATABASE = "database"
    TOOL_EXECUTION = "tool_execution"
    PLAN_EXECUTION = "plan_execution"


@dataclass
class TimeoutConfig:
    """Configuration for a specific timeout type."""
    timeout_type: TimeoutType
    default_seconds: float
    min_seconds: float = 0.1
    max_seconds: float = 300.0  # 5 minutes max for any single operation
    description: str = ""


def _can_use_sigalrm() -> bool:
    """SIGALRM is Unix-only and main-thread-only."""
    if not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"):
        return False
    return threading.current_thread() is threading.main_thread()


class TimeoutManager:
    """Manages timeout configurations and provides timeout contexts."""

    def __init__(self):
        # Default timeout configurations
        self._configs = {
            TimeoutType.AI_REQUEST: TimeoutConfig(
                TimeoutType.AI_REQUEST, 30.0, 5.0, 120.0, "AI model request timeout"
            ),
            TimeoutType.STT: TimeoutConfig(
                TimeoutType.STT, 10.0, 2.0, 30.0, "Speech-to-text transcription timeout"
            ),
            TimeoutType.TTS: TimeoutConfig(
                TimeoutType.TTS, 15.0, 2.0, 60.0, "Text-to-speech synthesis timeout"
            ),
            TimeoutType.BROWSER: TimeoutConfig(
                TimeoutType.BROWSER, 30.0, 5.0, 120.0, "Browser automation timeout"
            ),
            TimeoutType.TERMINAL: TimeoutConfig(
                TimeoutType.TERMINAL, 60.0, 5.0, 300.0, "Terminal command execution timeout"
            ),
            TimeoutType.FILE_OPERATION: TimeoutConfig(
                TimeoutType.FILE_OPERATION, 10.0, 1.0, 60.0, "File read/write operation timeout"
            ),
            TimeoutType.NETWORK: TimeoutConfig(
                TimeoutType.NETWORK, 15.0, 2.0, 60.0, "Network operation timeout"
            ),
            TimeoutType.DATABASE: TimeoutConfig(
                TimeoutType.DATABASE, 5.0, 1.0, 30.0, "Database operation timeout"
            ),
            TimeoutType.TOOL_EXECUTION: TimeoutConfig(
                TimeoutType.TOOL_EXECUTION, 30.0, 5.0, 120.0, "Individual tool execution timeout"
            ),
            TimeoutType.PLAN_EXECUTION: TimeoutConfig(
                TimeoutType.PLAN_EXECUTION, 300.0, 30.0, 1800.0, "Multi-step plan execution timeout"
            ),
        }

        # Allow override of timeout values
        self._overrides: dict[TimeoutType, float] = {}

    def set_timeout(self, timeout_type: TimeoutType, seconds: float) -> None:
        """Override the timeout value for a specific type."""
        if timeout_type in self._configs:
            config = self._configs[timeout_type]
            overridden = max(config.min_seconds, min(seconds, config.max_seconds))
            self._overrides[timeout_type] = overridden
        else:
            raise ValueError(f"Unknown timeout type: {timeout_type}")

    def get_timeout(self, timeout_type: TimeoutType) -> float:
        """Get the effective timeout value for a type."""
        if timeout_type in self._overrides:
            return self._overrides[timeout_type]

        if timeout_type in self._configs:
            return self._configs[timeout_type].default_seconds

        # Default fallback
        return 30.0

    def get_config(self, timeout_type: TimeoutType) -> Optional[TimeoutConfig]:
        """Get the full configuration for a timeout type."""
        return self._configs.get(timeout_type)

    @contextmanager
    def timeout_context(
        self,
        timeout_type: TimeoutType,
        timeout_seconds: Optional[float] = None,
        on_timeout: Optional[Callable[[], None]] = None,
    ) -> Iterator[None]:
        """Enforce a timeout. Uses SIGALRM only on the main thread.

        On worker threads (voice command path), this is a no-op wrapper —
        callers should pass timeout= to subprocess.run / requests instead.
        """
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self.get_timeout(timeout_type)
        )

        if not _can_use_sigalrm():
            # Worker thread / unsupported platform: do not touch signal module.
            try:
                yield
            except TimeoutError:
                if on_timeout:
                    try:
                        on_timeout()
                    except Exception:
                        pass
                raise
            return

        def timeout_handler(signum, frame):  # noqa: ANN001
            raise TimeoutError(
                f"{timeout_type.value} operation timed out after {timeout} seconds"
            )

        try:
            old_handler = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.setitimer(signal.ITIMER_REAL, timeout)
        except ValueError:
            # "signal only works in main thread" — treat as no-op context
            yield
            return

        try:
            yield
        except TimeoutError:
            if on_timeout:
                try:
                    on_timeout()
                except Exception:
                    pass
            raise
        finally:
            try:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, old_handler)
            except ValueError:
                pass

    @contextmanager
    def subprocess_timeout(
        self,
        timeout_type: TimeoutType,
        timeout_seconds: Optional[float] = None,
    ) -> Iterator[Callable[[subprocess.Popen], None]]:
        """Context manager for subprocess operations with timeout."""
        del timeout_type, timeout_seconds

        def kill_process(proc: subprocess.Popen) -> None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            except Exception:
                pass

        yield kill_process

    @contextmanager
    def thread_timeout(
        self,
        timeout_type: TimeoutType,
        timeout_seconds: Optional[float] = None,
    ) -> Iterator[None]:
        """Context manager placeholder for thread operations."""
        del timeout_type, timeout_seconds
        yield


# Global timeout manager instance
timeout_manager = TimeoutManager()


def with_timeout(
    timeout_type: TimeoutType,
    timeout_seconds: Optional[float] = None,
    on_timeout: Optional[Callable[[], None]] = None,
):
    """Decorator to add timeout functionality to a function."""

    def decorator(func):
        def wrapper(*args, **kwargs):
            with timeout_manager.timeout_context(
                timeout_type, timeout_seconds, on_timeout
            ):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def execute_with_timeout(
    func: Callable,
    timeout_type: TimeoutType,
    timeout_seconds: Optional[float] = None,
    *args,
    **kwargs,
) -> Any:
    """Execute a function with timeout protection (thread-safe via pool)."""
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else timeout_manager.get_timeout(timeout_type)
    )
    if _can_use_sigalrm():
        with timeout_manager.timeout_context(timeout_type, timeout):
            return func(*args, **kwargs)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeout as err:
            raise TimeoutError(
                f"{timeout_type.value} operation timed out after {timeout} seconds"
            ) from err
