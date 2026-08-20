"""Centralized error handling system for JARVIS 2.0.

Provides error classification, user-friendly messaging, and developer logging
without exposing raw exceptions to users.
"""

from __future__ import annotations

import enum
import traceback
from dataclasses import dataclass
from typing import Optional


class ErrorType(enum.Enum):
    """Classification of errors for appropriate handling and user messaging."""
    NETWORK_ERROR = "network_error"
    TIMEOUT_ERROR = "timeout_error"
    FILE_ERROR = "file_error"
    PERMISSION_ERROR = "permission_error"
    TOOL_ERROR = "tool_error"
    MODEL_ERROR = "model_error"
    AUTH_ERROR = "auth_error"
    DATABASE_ERROR = "database_error"
    VOICE_ERROR = "voice_error"
    STT_ERROR = "stt_error"
    TTS_ERROR = "tts_error"
    VALIDATION_ERROR = "validation_error"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class ErrorInfo:
    """Structured error information for logging and user communication."""
    error_type: ErrorType
    user_message: str  # User-friendly message in appropriate language
    developer_message: str  # Detailed message for logs
    exception: Optional[Exception] = None
    context: Optional[dict] = None  # Additional context for debugging


class ErrorHandler:
    """Centralized error handling and classification system."""

    def __init__(self):
        self._error_mappings = {
            # Network-related errors
            ConnectionError: ErrorType.NETWORK_ERROR,
            TimeoutError: ErrorType.TIMEOUT_ERROR,

            # File system errors
            FileNotFoundError: ErrorType.FILE_ERROR,
            PermissionError: ErrorType.PERMISSION_ERROR,
            IsADirectoryError: ErrorType.FILE_ERROR,
            NotADirectoryError: ErrorType.FILE_ERROR,

            # Database errors would be added when DB layer is defined

            # Default fallback
        }

    def classify_error(self, exception: Exception) -> ErrorType:
        """Classify an exception into an ErrorType based on its type."""
        # Check exact type match first
        for exc_type, error_type in self._error_mappings.items():
            if isinstance(exception, exc_type):
                return error_type

        # Check inheritance
        for exc_type, error_type in self._error_mappings.items():
            if isinstance(exception, exc_type):
                return error_type

        # Fallback to unknown
        return ErrorType.UNKNOWN_ERROR

    def get_user_message(self, error_type: ErrorType, context: Optional[dict] = None, language: str = "en") -> str:
        """Get user-friendly message in specified language."""
        context = context or {}

        # Base messages in English
        en_messages = {
            ErrorType.NETWORK_ERROR: "Network connection issue. Please check your internet connection and try again.",
            ErrorType.TIMEOUT_ERROR: "Operation timed out. Please try again.",
            ErrorType.FILE_ERROR: "File or directory issue. Please check the file path and permissions.",
            ErrorType.PERMISSION_ERROR: "Permission denied. Please check your access rights.",
            ErrorType.TOOL_ERROR: "Tool execution failed. Please try again or contact support if the issue persists.",
            ErrorType.MODEL_ERROR: "AI model unavailable. Please wait a moment and try again.",
            ErrorType.AUTH_ERROR: "Authentication error. Please check your credentials.",
            ErrorType.DATABASE_ERROR: "Database error. Please try again later.",
            ErrorType.VOICE_ERROR: "Voice system issue. Please check your microphone and speakers.",
            ErrorType.STT_ERROR: "Speech recognition issue. Please try speaking again.",
            ErrorType.TTS_ERROR: "Text-to-speech issue. Please try again.",
            ErrorType.VALIDATION_ERROR: "Input validation error. Please check your command and try again.",
            ErrorType.UNKNOWN_ERROR: "An unexpected error occurred. Please try again."
        }

        # Turkish translations
        tr_messages = {
            ErrorType.NETWORK_ERROR: "Ağ bağlantısı sorunu. Lütfen internet bağlantınızı kontrol edin ve tekrar deneyin.",
            ErrorType.TIMEOUT_ERROR: "İşlem zaman aşımına uğradı. Lütfen tekrar deneyin.",
            ErrorType.FILE_ERROR: "Dosya veya dizin sorunu. Lütfen dosya yolunu ve izinleri kontrol edin.",
            ErrorType.PERMISSION_ERROR: "İzin reddedildi. Lütfen erişim haklarınızı kontrol edin.",
            ErrorType.TOOL_ERROR: "Araç çalıştırma başarısız oldu. Lütfen tekrar deneyin veya sorun devam ederse destekle iletişim kurun.",
            ErrorType.MODEL_ERROR: "Yapay zeka modeli kullanılamıyor. Lütfen bir moment bekleyip tekrar deneyin.",
            ErrorType.AUTH_ERROR: "Kimlik doğrulama hatası. Lütfen kimlik bilgilerinizi kontrol edin.",
            ErrorType.DATABASE_ERROR: "Veritabanı hatası. Lütfen daha sonra tekrar deneyin.",
            ErrorType.VOICE_ERROR: "Ses sistemi sorunu. Lütfen mikrofon ve hoparlörünüzü kontrol edin.",
            ErrorType.STT_ERROR: "Konuşma tanıma sorunu. Lütfen tekrar konuşarak deneyin.",
            ErrorType.TTS_ERROR: "Metin-ten-ses sistemas sorunu. Lütfen tekrar deneyin.",
            ErrorType.VALIDATION_ERROR: "Giriş doğrulama hatası. Lütfen komutunuzu kontrol edin ve tekrar deneyin.",
            ErrorType.UNKNOWN_ERROR: "Beklenmeyen bir hata oluştu. Lütfen tekrar deneyin."
        }

        messages = tr_messages if language.startswith("tr") else en_messages
        base_message = messages.get(error_type, messages[ErrorType.UNKNOWN_ERROR])

        # Add context-specific information if available
        if context:
            if "tool_name" in context:
                base_message += f" (Araç: {context['tool_name']})"
            if "filename" in context:
                base_message += f" (Dosya: {context['filename']})"
            if "app_name" in context:
                base_message += f" (Uygulama: {context['app_name']})"

        return base_message

    def handle_error(self, exception: Exception, context: Optional[dict] = None, language: str = "en") -> ErrorInfo:
        """Handle an exception and return structured error information."""
        error_type = self.classify_error(exception)

        # Get user and developer messages
        user_message = self.get_user_message(error_type, context, language)

        # Developer message includes full exception details
        developer_message = f"{type(exception).__name__}: {str(exception)}"
        if context:
            developer_message += f" | Context: {context}"

        # Always log the full traceback for developers
        print(f"ERROR HANDLED: {developer_message}")
        print(f"TRACEBACK: {traceback.format_exc()}")

        return ErrorInfo(
            error_type=error_type,
            user_message=user_message,
            developer_message=developer_message,
            exception=exception,
            context=context
        )


# Global error handler instance
error_handler = ErrorHandler()


def handle_error(exception: Exception, context: Optional[dict] = None, language: str = "en") -> ErrorInfo:
    """Convenience function to handle errors using the global error handler."""
    return error_handler.handle_error(exception, context, language)


def safe_execute(func, *args, context: Optional[dict] = None, language: str = "en", **kwargs):
    """Execute a function safely, catching and handling any exceptions."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        error_info = handle_error(e, context, language)
        # Re-raise as a controlled exception if needed, or return error info
        # For now, we'll return the error info so callers can decide what to do
        return error_info