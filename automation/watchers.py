"""Filesystem event polling for automation (stdlib only)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class FileEvent:
    path: str
    name: str
    rule_id: int


@dataclass
class WatchState:
    """Per-rule seen paths (in-memory; survives until process restart)."""

    seen: set[str] = field(default_factory=set)
    seeded: bool = False


class FileWatchService:
    """Poll watched folders for newly appeared files matching a pattern."""

    def __init__(self) -> None:
        self._states: dict[int, WatchState] = {}

    def reset(self, rule_id: int) -> None:
        self._states.pop(rule_id, None)

    def poll(self, rule_id: int, trigger_spec: dict[str, Any]) -> list[FileEvent]:
        """Return new files since last poll. First poll seeds without firing."""
        raw_path = str(trigger_spec.get("path") or "~/Downloads").strip() or "~/Downloads"
        pattern = str(trigger_spec.get("pattern") or "*").strip() or "*"
        folder = Path(raw_path).expanduser()
        if not folder.exists() or not folder.is_dir():
            return []

        state = self._states.setdefault(rule_id, WatchState())
        matches = self._list_matches(folder, pattern)

        if not state.seeded:
            state.seen = set(matches)
            state.seeded = True
            return []

        new_paths = [p for p in matches if p not in state.seen]
        # Mark all current as seen (including new)
        state.seen.update(matches)
        # Bound memory
        if len(state.seen) > 5000:
            state.seen = set(matches)

        events: list[FileEvent] = []
        for p in new_paths:
            path = Path(p)
            # Skip incomplete downloads (common .download / .crdownload)
            if path.suffix.lower() in {".download", ".crdownload", ".tmp", ".part"}:
                continue
            # Optional settle: file size stable
            settle = float(trigger_spec.get("settle_seconds") or 0)
            if settle > 0 and not self._settled(path, settle):
                # Leave unseen so next poll can retry
                state.seen.discard(p)
                continue
            events.append(FileEvent(path=p, name=path.name, rule_id=rule_id))
        return events

    @staticmethod
    def _list_matches(folder: Path, pattern: str) -> list[str]:
        # Support "*.pdf" or "pdf" or "*"
        pat = pattern
        if pat.startswith("."):
            pat = f"*{pat}"
        elif pat.isalnum():
            pat = f"*.{pat}"
        try:
            return sorted(str(p.resolve()) for p in folder.glob(pat) if p.is_file())
        except OSError:
            logger.exception("file watch glob failed for %s", folder)
            return []

    @staticmethod
    def _settled(path: Path, seconds: float) -> bool:
        try:
            s1 = path.stat().st_size
            time.sleep(min(seconds, 2.0))
            s2 = path.stat().st_size
            return s1 == s2
        except OSError:
            return False
