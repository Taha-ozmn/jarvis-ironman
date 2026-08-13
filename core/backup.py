"""Versioned SQLite + YAML backups (Phase 7)."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class BackupResult:
    ok: bool
    path: str = ""
    message: str = ""
    files: list[str] | None = None


class BackupService:
    """Copy DB + critical YAML into data/backups/<timestamp>/ with retention."""

    def __init__(
        self,
        *,
        db_path: Path,
        root: Optional[Path] = None,
        backup_dir: Optional[Path] = None,
        retention: int = 10,
    ) -> None:
        self.root = root or ROOT
        self.db_path = Path(db_path)
        self.backup_dir = backup_dir or (self.root / "data" / "backups")
        self.retention = max(1, int(retention))

    def run(self) -> BackupResult:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.backup_dir / stamp
        try:
            target.mkdir(parents=True, exist_ok=True)
            copied: list[str] = []
            if self.db_path.exists():
                dest = target / self.db_path.name
                shutil.copy2(self.db_path, dest)
                copied.append(dest.name)
                # WAL sidecar if present
                for suffix in ("-wal", "-shm"):
                    side = Path(str(self.db_path) + suffix)
                    if side.exists():
                        shutil.copy2(side, target / side.name)
                        copied.append(side.name)
            else:
                logger.warning("DB missing for backup: %s", self.db_path)

            for rel in (
                "config/projects.yaml",
                "config.yaml",
            ):
                src = self.root / rel
                if src.exists():
                    # Flatten name to avoid nested dirs complexity
                    name = rel.replace("/", "__")
                    shutil.copy2(src, target / name)
                    copied.append(name)

            # Automations live in SQLite; also dump a lightweight marker
            (target / "MANIFEST.txt").write_text(
                f"jarvis-backup\ncreated={stamp}\nfiles={','.join(copied)}\n",
                encoding="utf-8",
            )
            copied.append("MANIFEST.txt")
            self._prune()
            return BackupResult(
                ok=True,
                path=str(target),
                message=f"Backup saved ({len(copied)} files) → {target.name}",
                files=copied,
            )
        except Exception as err:
            logger.exception("backup failed")
            return BackupResult(ok=False, message=str(err))

    def _prune(self) -> None:
        if not self.backup_dir.exists():
            return
        dirs = sorted(
            [p for p in self.backup_dir.iterdir() if p.is_dir()],
            key=lambda p: p.name,
        )
        while len(dirs) > self.retention:
            old = dirs.pop(0)
            try:
                shutil.rmtree(old)
            except OSError:
                logger.exception("failed to prune backup %s", old)

    def list_backups(self, *, limit: int = 10) -> list[dict[str, Any]]:
        if not self.backup_dir.exists():
            return []
        dirs = sorted(
            [p for p in self.backup_dir.iterdir() if p.is_dir()],
            key=lambda p: p.name,
            reverse=True,
        )
        out: list[dict[str, Any]] = []
        for d in dirs[:limit]:
            out.append({"name": d.name, "path": str(d)})
        return out
