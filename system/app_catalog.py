"""Discover and resolve installed macOS applications — no whitelist."""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class InstalledApp:
    """A macOS .app bundle on disk."""

    name: str
    path: Path


_CATALOG: Optional["AppCatalog"] = None


class AppCatalog:
    """Scan /Applications (+ system + user) and fuzzy-match spoken app names."""

    SEARCH_DIRS = (
        Path("/Applications"),
        Path("/System/Applications"),
        Path("/System/Applications/Utilities"),
        Path.home() / "Applications",
    )
    CACHE_TTL_SEC = 300

    def __init__(self) -> None:
        self._apps: list[InstalledApp] = []
        self._by_name_lower: dict[str, InstalledApp] = {}
        self._loaded_at: float = 0.0

    def refresh(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and self._apps and (now - self._loaded_at) < self.CACHE_TTL_SEC:
            return
        found: dict[str, InstalledApp] = {}
        for root in self.SEARCH_DIRS:
            self._scan_dir(root, found)
        self._apps = sorted(found.values(), key=lambda a: a.name.lower())
        self._by_name_lower = {a.name.lower(): a for a in self._apps}
        self._loaded_at = now

    @staticmethod
    def _scan_dir(root: Path, found: dict[str, InstalledApp]) -> None:
        if not root.is_dir():
            return
        try:
            for entry in root.iterdir():
                if not entry.name.endswith(".app"):
                    continue
                if not entry.is_dir():
                    continue
                key = entry.stem.lower()
                found.setdefault(key, InstalledApp(name=entry.stem, path=entry))
        except OSError:
            return

    def list_names(self, *, limit: int = 200) -> list[str]:
        self.refresh()
        return [a.name for a in self._apps[: max(1, limit)]]

    def resolve(
        self,
        query: str,
        *,
        aliases: Optional[dict[str, str]] = None,
    ) -> Optional[InstalledApp]:
        """Best match for a spoken or typed app name."""
        raw = (query or "").strip()
        if not raw:
            return None

        from core.open_target import SITE_OPEN_URLS, normalize_open_target

        normalized = normalize_open_target(raw)
        lower = normalized.lower().strip()
        if lower in SITE_OPEN_URLS:
            return None

        alias_map = aliases or {}
        if lower in alias_map:
            lower = alias_map[lower].lower()
        elif normalized.lower() in alias_map:
            lower = alias_map[normalized.lower()].lower()

        self.refresh()

        exact = self._by_name_lower.get(lower)
        if exact is not None:
            return exact

        # Alias values may be display names not yet indexed
        for alias_key, app_name in alias_map.items():
            if lower == alias_key or lower == app_name.lower():
                hit = self._by_name_lower.get(app_name.lower())
                if hit is not None:
                    return hit

        best: Optional[InstalledApp] = None
        best_score = 0.0
        for app in self._apps:
            score = _match_score(lower, app.name.lower())
            if score > best_score:
                best_score = score
                best = app

        if best is not None and best_score >= 55.0:
            return best

        mdfind_hit = self.spotlight_find(query)
        if mdfind_hit is not None:
            return mdfind_hit

        return None

    def spotlight_find(self, query: str) -> Optional[InstalledApp]:
        """Last-resort Spotlight lookup for an application bundle."""
        return self._mdfind(query)

    def suggest(self, query: str, *, limit: int = 5) -> list[str]:
        """Return near-miss app names for error messages."""
        lower = (query or "").strip().lower()
        if not lower:
            return []
        self.refresh()
        scored: list[tuple[float, str]] = []
        for app in self._apps:
            score = _match_score(lower, app.name.lower())
            if score >= 25.0:
                scored.append((score, app.name))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [name for _, name in scored[:limit]]

    @staticmethod
    def _mdfind(query: str) -> Optional[InstalledApp]:
        safe = query.replace("\\", "\\\\").replace('"', '\\"')
        expr = f"kMDItemKind == 'Application' && kMDItemDisplayName == '*{safe}*'cd"
        try:
            result = subprocess.run(
                ["mdfind", expr],
                capture_output=True,
                text=True,
                timeout=8,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        for line in (result.stdout or "").splitlines():
            path = Path(line.strip())
            if path.suffix == ".app" and path.is_dir():
                return InstalledApp(name=path.stem, path=path)
        return None


def get_app_catalog() -> AppCatalog:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = AppCatalog()
    return _CATALOG


def resolve_app_query(
    query: str,
    *,
    aliases: Optional[dict[str, str]] = None,
) -> Optional[InstalledApp]:
    return get_app_catalog().resolve(query, aliases=aliases)


def _match_score(query: str, name: str) -> float:
    if not query or not name:
        return 0.0
    if query == name:
        return 100.0
    if name.startswith(query) or query.startswith(name):
        return 85.0
    if len(query) >= 3 and (query in name or name in query):
        if query in name and not (name.startswith(query) or name.endswith(query)):
            return 38.0
        return 70.0
    q_tokens = set(re.split(r"[\s\-_]+", query))
    n_tokens = set(re.split(r"[\s\-_]+", name))
    overlap = q_tokens & n_tokens
    if overlap:
        return 50.0 + 12.0 * len(overlap)
    common = sum(1 for c in query if c in name)
    ratio = common / max(len(query), len(name))
    if ratio >= 0.75:
        return 40.0 + ratio * 15.0
    return ratio * 30.0
