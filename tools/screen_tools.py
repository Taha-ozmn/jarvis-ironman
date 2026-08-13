"""Screen awareness — on-demand capture + OCR/vision with honest fallback."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult
from tools.vision import capture_screen, ocr_image, vision_status

DescribeImageFn = Callable[[Path], str]


class ScreenCaptureTool(BaseTool):
    name = "screen.capture"
    description = "Capture the screen to a PNG via macOS screencapture (on demand)"
    permission_level = PermissionLevel.LOCAL
    input_schema: dict = {}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        out = str(arguments.get("path") or "").strip()
        if out:
            path = Path(out).expanduser()
        else:
            path = Path(tempfile.gettempdir()) / "jarvis-screen.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        ok, msg = capture_screen(path)
        if not ok:
            return ToolResult(ok=False, error=msg)
        return ToolResult(ok=True, data=f"Screen captured to {msg}")


class ScreenDescribeTool(BaseTool):
    name = "screen.describe"
    description = (
        "On-demand screen describe: OCR (tesseract) when available, "
        "else frontmost app metadata — never invents pixel content"
    )
    permission_level = PermissionLevel.LOCAL
    input_schema: dict = {}

    def __init__(self, llm_describe: Optional[DescribeImageFn] = None) -> None:
        self._llm_describe = llm_describe

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        status = vision_status()
        # 1) Capture
        path = Path(tempfile.gettempdir()) / "jarvis-screen-describe.png"
        ok, msg = capture_screen(path)
        meta = frontmost_app_info() or {}
        meta_line = _format_meta(meta)

        if not ok:
            # Capture failed — metadata only
            if meta:
                return ToolResult(
                    ok=True,
                    data=(
                        f"{meta_line}. Capture failed ({msg}). "
                        f"OCR unavailable path — metadata only."
                    ),
                )
            return ToolResult(ok=False, error=msg)

        # 2) Optional LLM vision
        if self._llm_describe is not None:
            try:
                desc = self._llm_describe(path)
                if desc and desc.strip():
                    return ToolResult(
                        ok=True,
                        data=f"{desc.strip()} ({meta_line})",
                    )
            except Exception:
                pass

        # 3) OCR via tesseract
        ocr = ocr_image(path)
        if ocr:
            excerpt = " ".join(ocr.split())
            if len(excerpt) > 320:
                excerpt = excerpt[:317] + "…"
            return ToolResult(
                ok=True,
                data=f"OCR: {excerpt}. Context: {meta_line}.",
            )

        # 4) Honest fallback
        note = status.get("note") or "OCR not available"
        return ToolResult(
            ok=True,
            data=(
                f"{meta_line}. "
                f"Pixel/OCR vision unavailable — {note}"
            ),
        )


def frontmost_app_info() -> Optional[dict[str, str]]:
    import subprocess

    script = """
    tell application "System Events"
      set frontApp to first application process whose frontmost is true
      set appName to name of frontApp
      set appBundle to bundle identifier of frontApp
      try
        set winTitle to name of front window of frontApp
      on error
        set winTitle to ""
      end try
      return appName & tab & appBundle & tab & winTitle
    end tell
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    parts = (result.stdout or "").strip().split("\t")
    while len(parts) < 3:
        parts.append("")
    return {"name": parts[0], "bundle": parts[1], "title": parts[2]}


def _format_meta(info: dict[str, str]) -> str:
    if not info:
        return "Frontmost app: unknown"
    name = info.get("name") or "Unknown"
    title = info.get("title") or ""
    parts = [f"Frontmost app: {name}"]
    if title:
        parts.append(f"window «{title}»")
    return ". ".join(parts)
