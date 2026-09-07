"""Screen awareness — on-demand capture + OCR/vision with honest fallback."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult
from tools.vision import (
    SCREEN_RECORDING_HELP_EN,
    capture_screen,
    is_screen_permission_error,
    ocr_image,
    vision_status,
)

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
            if is_screen_permission_error(msg):
                return ToolResult(ok=False, error=SCREEN_RECORDING_HELP_EN)
            return ToolResult(ok=False, error=msg)
        return ToolResult(ok=True, data=f"Screenshot captured: {msg}")


class ScreenDescribeTool(BaseTool):
    name = "screen.describe"
    description = (
        "On-demand screen describe: prefer cached frontmost context, "
        "else OCR/vision — never invents pixel content"
    )
    permission_level = PermissionLevel.LOCAL
    input_schema: dict = {
        "force": {"type": "bool", "required": False},
        "use_cache": {"type": "bool", "required": False},
    }

    def __init__(
        self,
        llm_describe: Optional[DescribeImageFn] = None,
        *,
        context_getter: Optional[Callable[[], dict[str, Any]]] = None,
        cache_max_age_sec: float = 12.0,
    ) -> None:
        self._llm_describe = llm_describe
        self._context_getter = context_getter
        self._cache_max_age_sec = max(3.0, float(cache_max_age_sec))

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        force = bool(arguments.get("force"))
        use_cache = arguments.get("use_cache")
        if use_cache is None:
            use_cache = not force

        if use_cache and not force:
            cached = self._cached_reply()
            if cached is not None:
                return ToolResult(ok=True, data=cached)

        status = vision_status()
        path = Path(tempfile.gettempdir()) / "jarvis-screen-describe.png"
        ok, msg = capture_screen(path)
        meta = frontmost_app_info() or {}
        app_name = (meta.get("name") or "").strip()
        title = (meta.get("title") or "").strip()

        if not ok:
            if is_screen_permission_error(msg):
                if app_name:
                    return ToolResult(
                        ok=True,
                        data=(
                            f"{app_name} is in the foreground"
                            + (f" («{title}»)" if title else "")
                            + ", but Screen Recording permission is missing. "
                            + SCREEN_RECORDING_HELP_EN
                        ),
                    )
                return ToolResult(ok=False, error=SCREEN_RECORDING_HELP_EN)
            if app_name:
                return ToolResult(
                    ok=True,
                    data=(
                        f"Yes — {app_name} is in the foreground"
                        + (f" («{title}»)" if title else "")
                        + f". Screen capture failed ({msg})."
                    ),
                )
            return ToolResult(ok=False, error=msg)

        see_line = (
            f"Yes, I can see your screen. {app_name or 'an unknown app'} is in the foreground"
            + (f" («{title}»)" if title else "")
            + "."
        )

        if self._llm_describe is not None:
            try:
                desc = self._llm_describe(path)
                if desc and desc.strip():
                    return ToolResult(ok=True, data=f"{see_line} {desc.strip()}")
            except Exception:
                pass

        ocr = ocr_image(path)
        if ocr:
            excerpt = " ".join(ocr.split())
            if len(excerpt) > 320:
                excerpt = excerpt[:317] + "…"
            return ToolResult(ok=True, data=f"{see_line} OCR on-screen text: {excerpt}")

        note = status.get("note") or ""
        extra = f" ({note})" if note and "tesseract" in note.lower() and "not" in note.lower() else ""
        return ToolResult(ok=True, data=f"{see_line}{extra}")

    def _cached_reply(self) -> Optional[str]:
        if self._context_getter is None:
            return None
        try:
            ctx = self._context_getter() or {}
        except Exception:
            return None
        if not isinstance(ctx, dict) or not ctx.get("ok"):
            return None
        import time

        updated = float(ctx.get("updated_at") or 0)
        if updated and (time.time() - updated) > self._cache_max_age_sec:
            return None
        summary = str(ctx.get("summary") or "").strip()
        app = str(ctx.get("app") or "").strip()
        title = str(ctx.get("title") or "").strip()
        if summary:
            return f"Yes — {summary}"
        if app:
            return (
                f"Yes — {app} is in the foreground"
                + (f" («{title}»)" if title else "")
                + "."
            )
        return None


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
            timeout=3,
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
