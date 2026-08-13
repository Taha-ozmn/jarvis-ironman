"""On-demand screen vision helpers — OCR optional, never continuous."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DescribeImageFn = Callable[[Path], str]


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def vision_status() -> dict[str, Any]:
    tess = tesseract_available()
    return {
        "ocr": "tesseract" if tess else None,
        "tesseract": tess,
        "llm_vision": False,  # wired when provider exposes describe_image
        "fallback": "frontmost-app metadata",
        "note": (
            "Install tesseract (brew install tesseract) for OCR. "
            "Otherwise describe uses frontmost app metadata only."
            if not tess
            else "tesseract available for on-demand OCR"
        ),
    }


def ocr_image(path: Path, *, lang: str = "eng") -> Optional[str]:
    """Run tesseract OCR if binary exists. Returns None if unavailable."""
    if not path.exists():
        return None
    if not tesseract_available():
        return None
    try:
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", lang],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as err:
        logger.info("tesseract failed: %s", err)
        return None
    if result.returncode != 0:
        return None
    text = (result.stdout or "").strip()
    return text or None


def capture_screen(path: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["screencapture", "-x", str(path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        return False, "screencapture not available (macOS only)"
    except subprocess.TimeoutExpired:
        return False, "Screen capture timed out"
    if result.returncode != 0 or not path.exists():
        err = (result.stderr or result.stdout or "capture failed").strip()
        return False, err[:300]
    return True, str(path)
