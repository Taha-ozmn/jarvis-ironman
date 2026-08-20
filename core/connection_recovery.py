"""Connection recovery system for JARVIS 2.0.

Provides automatic reconnection and retry mechanisms for external service
connections including AI APIs, WebSockets, HTTP services, and MCP connections.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

T = TypeVar('T')


class ConnectionType(Enum):
    """Types of connections that can be managed."""
    AI_API = "ai_api"
    WEBSOCKET = "websocket"
    HTTP_CLIENT = "http_client"
    MCP_STDIO = "mcp_stdio"
    PLAYWRIGHT_BROWSER = "playwright_browser"


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_attempts: int = 3
    base_delay: float = 0.5  # seconds
    max_delay: float = 60.0  # seconds
    exponential_base: float = 2.0
    jitter: bool = True
    jitter_range: float = 0.1  # 10% jitter


@dataclass
class ConnectionState:
    """Tracks the state of a connection."""
    connection_type: ConnectionType
    is_connected: bool = False
    last_error: Optional[str] = None
    last_error_time: float = 0.0
    retry_count: int = 0
    last_success: float = 0.0
    total_failures: int = 0
    total_successes: int = 0


class ConnectionRecoveryManager:
    """Manages connection recovery for various external services."""

    def __init__(self):
        self._connections: dict[str, ConnectionState] = {}
        self._retry_configs: dict[ConnectionType, RetryConfig] = {
            ConnectionType.AI_API: RetryConfig(
                max_attempts=3,
                base_delay=1.0,
                max_delay=30.0,
                exponential_base=2.0
            ),
            ConnectionType.WEBSOCKET: RetryConfig(
                max_attempts=5,
                base_delay=0.5,
                max_delay=10.0,
                exponential_base=1.5
            ),
            ConnectionType.HTTP_CLIENT: RetryConfig(
                max_attempts=3,
                base_delay=0.5,
                max_delay=10.0,
                exponential_base=2.0
            ),
            ConnectionType.MCP_STDIO: RetryConfig(
                max_attempts=3,
                base_delay=2.0,
                max_delay=30.0,
                exponential_base=2.0
            ),
            ConnectionType.PLAYWRIGHT_BROWSER: RetryConfig(
                max_attempts=2,
                base_delay=1.0,
                max_delay=5.0,
                exponential_base=2.0
            )
        }

    def get_connection_state(self, connection_id: str) -> ConnectionState:
        """Get or create connection state for a connection ID."""
        if connection_id not in self._connections:
            # Default to HTTP client type if not specified
            self._connections[connection_id] = ConnectionState(
                connection_type=ConnectionType.HTTP_CLIENT
            )
        return self._connections[connection_id]

    def set_connection_type(self, connection_id: str, connection_type: ConnectionType) -> None:
        """Set the connection type for a connection ID."""
        state = self.get_connection_state(connection_id)
        state.connection_type = connection_type

    def _calculate_delay(self, attempt: int, config: RetryConfig) -> float:
        """Calculate delay for retry attempt with exponential backoff and jitter."""
        delay = min(
            config.base_delay * (config.exponential_base ** attempt),
            config.max_delay
        )

        if config.jitter:
            jitter_amount = delay * config.jitter_range
            delay += random.uniform(-jitter_amount, jitter_amount)

        return max(0.0, delay)

    def execute_with_recovery(
        self,
        connection_id: str,
        operation: Callable[[], T],
        *,
        connection_type: Optional[ConnectionType] = None,
        on_reconnect: Optional[Callable[[], None]] = None,
        on_failure: Optional[Callable[[Exception], None]] = None
    ) -> T:
        """Execute an operation with connection recovery and retry logic.

        Args:
            connection_id: Unique identifier for the connection
            operation: Callable that performs the operation and may raise exceptions
            connection_type: Type of connection (auto-detected if not provided)
            on_reconnect: Callback to execute on successful reconnection
            on_failure: Callback to execute on final failure

        Returns:
            Result of the operation

        Raises:
            Exception: The last exception if all retries are exhausted
        """
        state = self.get_connection_state(connection_id)
        if connection_type:
            state.connection_type = connection_type

        config = self._retry_configs[state.connection_type]
        last_exception: Optional[Exception] = None

        for attempt in range(config.max_attempts):
            try:
                result = operation()

                # Success - update state
                if not state.is_connected and state.retry_count > 0:
                    # We were disconnected but now succeeded
                    state.is_connected = True
                    if on_reconnect:
                        try:
                            on_reconnect()
                        except Exception as e:
                            # Don't let reconnect callback failures break the main operation
                            pass

                state.last_success = time.time()
                state.total_successes += 1
                state.retry_count = 0  # Reset retry count on success
                state.last_error = None

                return result

            except Exception as e:
                last_exception = e
                state.last_error = str(e)
                state.last_error_time = time.time()
                state.total_failures += 1
                state.retry_count += 1

                # Mark as disconnected on failure
                state.is_connected = False

                # If this was our last attempt, don't retry
                if attempt >= config.max_attempts - 1:
                    break

                # Calculate delay before retry
                delay = self._calculate_delay(attempt, config)
                time.sleep(delay)

        # All attempts exhausted
        if on_failure and last_exception:
            try:
                on_failure(last_exception)
            except Exception:
                # Don't let failure callback break error reporting
                pass

        raise last_exception if last_exception else RuntimeError("Operation failed with no exception")

    def is_healthy(self, connection_id: str) -> bool:
        """Check if a connection is considered healthy."""
        state = self.get_connection_state(connection_id)

        # Consider healthy if connected recently or has recent success
        if state.is_connected:
            return True

        # If we had a recent success within last 5 minutes, consider recovering
        if state.last_success > 0:
            time_since_success = time.time() - state.last_success
            if time_since_success < 300:  # 5 minutes
                return True

        return False

    def get_stats(self, connection_id: str) -> dict[str, Any]:
        """Get statistics for a connection."""
        state = self.get_connection_state(connection_id)
        return {
            "connection_id": connection_id,
            "connection_type": state.connection_type.value,
            "is_connected": state.is_connected,
            "retry_count": state.retry_count,
            "total_failures": state.total_failures,
            "total_successes": state.total_successes,
            "last_error": state.last_error,
            "last_error_time": state.last_error_time,
            "last_success": state.last_success,
            "health": self.is_healthy(connection_id)
        }


# Global connection recovery manager instance
connection_recovery = ConnectionRecoveryManager()


def with_connection_recovery(
    connection_id: str,
    *,
    connection_type: Optional[ConnectionType] = None,
    on_reconnect: Optional[Callable[[], None]] = None,
    on_failure: Optional[Callable[[Exception], None]] = None
):
    """Decorator to add connection recovery to a function."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args, **kwargs) -> T:
            return connection_recovery.execute_with_recovery(
                connection_id,
                lambda: func(*args, **kwargs),
                connection_type=connection_type,
                on_reconnect=on_reconnect,
                on_failure=on_failure
            )
        return wrapper
    return decorator