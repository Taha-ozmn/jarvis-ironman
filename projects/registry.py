"""Project registry — YAML seed + SQLite projects table."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from memory.database import Database

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROJECTS_YAML = ROOT / "config" / "projects.yaml"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Project:
    id: Optional[int]
    key: str
    name: str
    path: str
    description: str = ""
    aliases: list[str] | None = None
    exists: bool = False

    @property
    def available(self) -> bool:
        """Alias for exists — path present on disk."""
        return self.exists

    def resolved_path(self) -> Path:
        return Path(self.path).expanduser().resolve()


class ProjectRegistry:
    """Load projects from YAML, sync to SQLite, track active project."""

    def __init__(
        self,
        db: Database,
        *,
        yaml_path: Optional[Path] = None,
        context: Any = None,
    ) -> None:
        self._db = db
        self._yaml_path = yaml_path or DEFAULT_PROJECTS_YAML
        self._context = context
        self._by_key: dict[str, Project] = {}
        self._active_key: Optional[str] = None

    def load(self) -> list[Project]:
        seeded = self._load_yaml()
        for proj in seeded:
            self._upsert_sqlite(proj)
            self._by_key[proj.key] = proj
        # Also load any SQLite-only projects (dedupe by path)
        known_paths = {
            str(Path(p.path).expanduser()) for p in self._by_key.values()
        }
        for row in self._db.fetchall("SELECT * FROM projects ORDER BY id"):
            path = row["path"] or ""
            expanded = str(Path(path).expanduser()) if path else ""
            if expanded in known_paths:
                # Refresh id on matching YAML project
                for proj in self._by_key.values():
                    if str(Path(proj.path).expanduser()) == expanded:
                        proj.id = int(row["id"])
                        break
                continue
            key = self._key_from_row(row)
            if key in self._by_key:
                continue
            exists = Path(expanded).exists() if expanded else False
            self._by_key[key] = Project(
                id=int(row["id"]),
                key=key,
                name=row["name"],
                path=expanded or path,
                description=row["description"] or "",
                aliases=[],
                exists=exists,
            )
        return self.list_projects()

    def list_projects(self) -> list[Project]:
        return list(self._by_key.values())

    def get(self, key_or_name: str) -> Optional[Project]:
        needle = (key_or_name or "").strip().lower()
        if not needle:
            return None
        if needle in self._by_key:
            return self._by_key[needle]
        for proj in self._by_key.values():
            if proj.name.lower() == needle:
                return proj
            aliases = [a.lower() for a in (proj.aliases or [])]
            if needle in aliases:
                return proj
            if needle in proj.key.lower() or needle in proj.name.lower():
                return proj
        return None

    def set_active(self, key_or_name: str) -> Project:
        proj = self.get(key_or_name)
        if proj is None:
            raise KeyError(f"Unknown project: {key_or_name}")
        self._active_key = proj.key
        if self._context is not None:
            self._context.update(active_project_id=proj.id)
            self._context.set_extra("active_project_key", proj.key)
            self._context.set_extra("active_project_path", proj.path)
            self._context.set_extra("active_project_exists", proj.exists)
        return proj

    def active(self) -> Optional[Project]:
        if self._active_key and self._active_key in self._by_key:
            return self._by_key[self._active_key]
        if self._context is not None:
            key = self._context.get_extra("active_project_key")
            if key and key in self._by_key:
                return self._by_key[key]
        return None

    def get_active(self) -> Optional[Project]:
        return self.active()

    def working_dir(self, fallback: Optional[Path] = None) -> Path:
        active = self.active()
        if active and active.exists:
            return active.resolved_path()
        if fallback is not None:
            return fallback
        return Path.cwd()

    def _load_yaml(self) -> list[Project]:
        path = self._yaml_path
        if not path.exists():
            logger.warning("projects.yaml missing: %s", path)
            return []
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        items = raw.get("projects") or []
        projects: list[Project] = []
        for item in items:
            key = str(item.get("key") or "").strip()
            name = str(item.get("name") or key).strip()
            raw_path = str(item.get("path") or "").strip()
            if not key or not raw_path:
                continue
            expanded = str(Path(raw_path).expanduser())
            exists = Path(expanded).exists()
            projects.append(
                Project(
                    id=None,
                    key=key,
                    name=name,
                    path=expanded,
                    description=str(item.get("description") or ""),
                    aliases=[str(a) for a in (item.get("aliases") or [])],
                    exists=exists,
                )
            )
        return projects

    def _upsert_sqlite(self, proj: Project) -> None:
        # Match by name first (schema has no key column)
        row = self._db.fetchone(
            "SELECT id FROM projects WHERE name = ? OR path = ?",
            (proj.name, proj.path),
        )
        now = _utc_now()
        if row:
            self._db.execute(
                """
                UPDATE projects
                SET path = ?, description = ?, updated_at = ?
                WHERE id = ?
                """,
                (proj.path, proj.description, now, int(row["id"])),
            )
            self._db.commit()
            proj.id = int(row["id"])
        else:
            cur = self._db.execute(
                """
                INSERT INTO projects (name, path, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (proj.name, proj.path, proj.description, now, now),
            )
            self._db.commit()
            proj.id = int(cur.lastrowid)

    @staticmethod
    def _key_from_row(row: Any) -> str:
        name = str(row["name"] or "project")
        return name.lower().replace(" ", "_")
