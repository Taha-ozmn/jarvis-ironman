"""Utility functions for JARVIS tools."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from security.risk import is_credential_path, is_dangerous_path_op


def _expand(path: str, base: Optional[Path] = None) -> Path:
    """
    Expand and resolve a path string.

    Args:
        path: Path string to expand (may contain ~)
        base: Optional base path to resolve relative paths against

    Returns:
        Expanded and resolved Path object
    """
    path_obj = Path(path).expanduser()

    if base is not None and not path_obj.is_absolute():
        path_obj = base / path_obj

    return path_obj.resolve()


# Re-export the imported functions for backward compatibility with the import
__all__ = ["is_credential_path", "is_dangerous_path_op", "_expand"]