"""Structured logging system for JARVIS 2.0.

Provides JSON-formatted structured logging with consistent fields for
observability and debugging.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class LogLevel(Enum):
    """Log levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LogEvent(Enum):
    """Standard log events for JARVIS 2.0."""
    USER_INPUT = "USER_INPUT"
    VOICE_PARTIAL = "VOICE_PARTIAL"
    VOICE_FINAL = "VOICE_FINAL"
    INTENT_DETECTED = "INTENT_DETECTED"
    TASK_CREATED = "TASK_CREATED"
    TASK_STARTED = "TASK_STARTED"
    TOOL_STARTED = "TOOL_STARTED"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    TOOL_FAILED = "TOOL_FAILED"
    MODEL_REQUEST = "MODEL_REQUEST"
    MODEL_RESPONSE = "MODEL_RESPONSE"
    MODEL_SWITCHED = "MODEL_SWITCHED"
    STT_STARTED = "STT_STARTED"
    STT_COMPLETED = "STT_COMPLETED"
    TTS_STARTED = "TTS_STARTED"
    TTS_INTERRUPTED = "TTS_INTERRUPTED"
    ERROR = "ERROR"
    RETRY = "RETRY"
    RECOVERY = "RECOVERY"
    TASK_CANCELLED = "TASK_CANCELLED"
    TASK_COMPLETED = "TASK_COMPLETED"


@dataclass
class StructuredLogEntry:
    """A structured log entry."""
    timestamp: float = field(default_factory=time.time)
    task_id: Optional[str] = None
    execution_id: Optional[str] = None
    component: str = ""
    event: str = ""
    status: str = ""  # success, error, in_progress, etc.
    duration_ms: Optional[float] = None
    error_type: Optional[str] = None
    level: str = LogLevel.INFO.value
    message: str = ""
    # Additional fields can be added here as needed
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Convert to JSON string."""
        # Remove None values to keep output clean
        data = asdict(self)
        # Filter out None values
        data = {k: v for k, v in data.items() if v is not None}
        return json.dumps(data, ensure_ascii=False)


class StructuredLogger:
    """Thread-safe structured logger."""

    def __init__(self, name: str = "jarvis"):
        self._logger = logging.getLogger(name)
        self._lock = threading.Lock()

        # Only configure if not already configured
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(message)s')
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)
            self._logger.propagate = False

    def _log(
        self,
        level: LogLevel,
        event: LogEvent,
        component: str,
        message: str = "",
        *,
        task_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        status: str = "",
        duration_ms: Optional[float] = None,
        error_type: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> None:
        """Internal method to log a structured entry."""
        entry = StructuredLogEntry(
            timestamp=time.time(),
            task_id=task_id,
            execution_id=execution_id,
            component=component,
            event=event.value,
            status=status,
            duration_ms=duration_ms,
            error_type=error_type,
            level=level.value,
            message=message,
            extra=extra or {}
        )

        with self._lock:
            self._logger.log(
                getattr(logging, level.value.upper()),
                entry.to_json()
            )

    def debug(
        self,
        event: LogEvent,
        component: str,
        message: str = "",
        *,
        task_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        status: str = "",
        duration_ms: Optional[float] = None,
        error_type: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log a debug event."""
        self._log(
            LogLevel.DEBUG, event, component, message,
            task_id=task_id,
            execution_id=execution_id,
            status=status,
            duration_ms=duration_ms,
            error_type=error_type,
            extra=extra
        )

    def info(
        self,
        event: LogEvent,
        component: str,
        message: str = "",
        *,
        task_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        status: str = "",
        duration_ms: Optional[float] = None,
        error_type: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log an info event."""
        self._log(
            LogLevel.INFO, event, component, message,
            task_id=task_id,
            execution_id=execution_id,
            status=status,
            duration_ms=duration_ms,
            error_type=error_type,
            extra=extra
        )

    def warning(
        self,
        event: LogEvent,
        component: str,
        message: str = "",
        *,
        task_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        status: str = "",
        duration_ms: Optional[float] = None,
        error_type: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log a warning event."""
        self._log(
            LogLevel.WARNING, event, component, message,
            task_id=task_id,
            execution_id=execution_id,
            status=status,
            duration_ms=duration_ms,
            error_type=error_type,
            extra=extra
        )

    def error(
        self,
        event: LogEvent,
        component: str,
        message: str = "",
        *,
        task_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        status: str = "",
        duration_ms: Optional[float] = None,
        error_type: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log an error event."""
        self._log(
            LogLevel.ERROR, event, component, message,
            task_id=task_id,
            execution_id=execution_id,
            status=status,
            duration_ms=duration_ms,
            error_type=error_type,
            extra=extra
        )

    def critical(
        self,
        event: LogEvent,
        component: str,
        message: str = "",
        *,
        task_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        status: str = "",
        duration_ms: Optional[float] = None,
        error_type: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log a critical event."""
        self._log(
            LogLevel.CRITICAL, event, component, message,
            task_id=task_id,
            execution_id=execution_id,
            status=status,
            duration_ms=duration_ms,
            error_type=error_type,
            extra=extra
        )


# Global structured logger instance
structured_logger = StructuredLogger()


# Convenience functions for common logging patterns
def log_user_input(
    component: str,
    command: str,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log user input."""
    structured_logger.info(
        LogEvent.USER_INPUT,
        component,
        f"User input: {command}",
        task_id=task_id,
        execution_id=execution_id,
        status="received"
    )


def log_voice_partial(
    component: str,
    partial_text: str,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log voice partial recognition."""
    structured_logger.debug(
        LogEvent.VOICE_PARTIAL,
        component,
        f"Voice partial: {partial_text}",
        task_id=task_id,
        execution_id=execution_id,
        status="partial"
    )


def log_voice_final(
    component: str,
    final_text: str,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log voice final recognition."""
    structured_logger.info(
        LogEvent.VOICE_FINAL,
        component,
        f"Voice final: {final_text}",
        task_id=task_id,
        execution_id=execution_id,
        status="completed"
    )


def log_intent_detected(
    component: str,
    intent: str,
    confidence: float,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log intent detection."""
    structured_logger.info(
        LogEvent.INTENT_DETECTED,
        component,
        f"Intent detected: {intent} (confidence: {confidence:.2f})",
        task_id=task_id,
        execution_id=execution_id,
        status="detected",
        extra={"confidence": confidence}
    )


def log_task_created(
    component: str,
    task_description: str,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log task creation."""
    structured_logger.info(
        LogEvent.TASK_CREATED,
        component,
        f"Task created: {task_description}",
        task_id=task_id,
        execution_id=execution_id,
        status="created"
    )


def log_task_started(
    component: str,
    task_description: str,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log task start."""
    structured_logger.info(
        LogEvent.TASK_STARTED,
        component,
        f"Task started: {task_description}",
        task_id=task_id,
        execution_id=execution_id,
        status="started"
    )


def log_tool_started(
    component: str,
    tool_name: str,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log tool start."""
    structured_logger.info(
        LogEvent.TOOL_STARTED,
        component,
        f"Tool started: {tool_name}",
        task_id=task_id,
        execution_id=execution_id,
        status="started"
    )


def log_tool_completed(
    component: str,
    tool_name: str,
    success: bool,
    duration_ms: Optional[float] = None,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    error: Optional[str] = None
) -> None:
    """Log tool completion."""
    structured_logger.info(
        LogEvent.TOOL_COMPLETED if success else LogEvent.TOOL_FAILED,
        component,
        f"Tool {'completed' if success else 'failed'}: {tool_name}",
        task_id=task_id,
        execution_id=execution_id,
        status="success" if success else "error",
        duration_ms=duration_ms,
        error_type=error if not success else None,
        extra={"tool_name": tool_name, "success": success}
    )


def log_model_request(
    component: str,
    model: str,
    prompt: str,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log model request."""
    structured_logger.debug(
        LogEvent.MODEL_REQUEST,
        component,
        f"Model request: {model}",
        task_id=task_id,
        execution_id=execution_id,
        status="requested",
        extra={"model": model, "prompt_length": len(prompt)}
    )


def log_model_response(
    component: str,
    model: str,
    response: str,
    duration_ms: Optional[float] = None,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log model response."""
    structured_logger.info(
        LogEvent.MODEL_RESPONSE,
        component,
        f"Model response: {model}",
        task_id=task_id,
        execution_id=execution_id,
        status="completed",
        duration_ms=duration_ms,
        extra={"model": model, "response_length": len(response)}
    )


def log_model_switched(
    component: str,
    from_model: str,
    to_model: str,
    reason: str = "",
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log model switch."""
    structured_logger.info(
        LogEvent.MODEL_SWITCHED,
        component,
        f"Model switched from {from_model} to {to_model}: {reason}",
        task_id=task_id,
        execution_id=execution_id,
        status="switched",
        extra={"from_model": from_model, "to_model": to_model, "reason": reason}
    )


def log_stt_started(
    component: str,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log STT start."""
    structured_logger.info(
        LogEvent.STT_STARTED,
        component,
        "STT started",
        task_id=task_id,
        execution_id=execution_id,
        status="started"
    )


def log_stt_completed(
    component: str,
    result: str,
    duration_ms: Optional[float] = None,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log STT completion."""
    structured_logger.info(
        LogEvent.STT_COMPLETED,
        component,
        f"STT completed: {result}",
        task_id=task_id,
        execution_id=execution_id,
        status="completed",
        duration_ms=duration_ms
    )


def log_tts_started(
    component: str,
    text: str,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log TTS start."""
    structured_logger.info(
        LogEvent.TTS_STARTED,
        component,
        f"TTS started: {text[:50]}...",
        task_id=task_id,
        execution_id=execution_id,
        status="started",
        extra={"text_length": len(text)}
    )


def log_tts_interrupted(
    component: str,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log TTS interruption."""
    structured_logger.warning(
        LogEvent.TTS_INTERRUPTED,
        component,
        "TTS interrupted",
        task_id=task_id,
        execution_id=execution_id,
        status="interrupted"
    )


def log_error(
    component: str,
    error: str,
    error_type: Optional[str] = None,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log an error."""
    structured_logger.error(
        LogEvent.ERROR,
        component,
        f"Error: {error}",
        task_id=task_id,
        execution_id=execution_id,
        status="error",
        error_type=error_type
    )


def log_message(
    component: str,
    message: str,
    level: str = "info",
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log a generic message with specified level."""
    level_enum = LogLevel(level.lower()) if hasattr(LogLevel, level.upper()) else LogLevel.INFO
    structured_logger._log(
        level_enum,
        LogEvent.ERROR if level.lower() == "error" else LogEvent.USER_INPUT,  # Using appropriate event types
        component,
        message,
        task_id=task_id,
        execution_id=execution_id
    )


def log_retry(
    component: str,
    attempt: int,
    max_attempts: int,
    reason: str = "",
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log a retry attempt."""
    structured_logger.info(
        LogEvent.RETRY,
        component,
        f"Retry attempt {attempt}/{max_attempts}: {reason}",
        task_id=task_id,
        execution_id=execution_id,
        status="retrying",
        extra={"attempt": attempt, "max_attempts": max_attempts, "reason": reason}
    )


def log_recovery(
    component: str,
    action: str,
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log recovery action."""
    structured_logger.info(
        LogEvent.RECOVERY,
        component,
        f"Recovery: {action}",
        task_id=task_id,
        execution_id=execution_id,
        status="recovered",
        extra={"action": action}
    )


def log_task_cancelled(
    component: str,
    reason: str = "",
    *,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None
) -> None:
    """Log task cancellation."""
    structured_logger.info(
        LogEvent.TASK_CANCELLED,
        component,
        f"Task cancelled: {reason}",
        task_id=task_id,
        execution_id=execution_id,
        status="cancelled",
        extra={"reason": reason}
    )


