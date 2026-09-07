"""Safe, proposal-driven self-improvement workflow for JARVIS."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from memory.extractor import redact_secrets

logger = logging.getLogger(__name__)


@dataclass
class ImprovementProposal:
    """A bounded improvement request that still needs user approval."""

    proposal_id: str
    title: str
    reason: str
    scope: str
    status: str = "proposed"  # proposed | testing | tested | approved | rejected
    worktree: str = ""
    test_output: str = ""
    created_at: float = 0.0


class SelfImprovementEngine:
    """Observe failures and prepare isolated, reviewable improvements."""

    SAFE_SCOPES = frozenset(
        {"persona", "retrieval", "retry_policy", "performance", "bug_fix"}
    )

    def __init__(
        self,
        root: Path,
        *,
        state_path: Optional[Path] = None,
        worktree_root: Optional[Path] = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.state_path = Path(
            state_path or self.root / "data" / "improvement_proposals.json"
        ).resolve()
        try:
            self.state_path.relative_to(self.root)
        except ValueError as err:
            raise ValueError("Improvement state must stay inside the project root") from err
        self.worktree_root = Path(
            worktree_root or self.root / "data" / "improvement_worktrees"
        ).resolve()
        try:
            self.worktree_root.relative_to(self.root)
        except ValueError as err:
            raise ValueError("Improvement worktrees must stay inside the project root") from err
        self._proposals: dict[str, ImprovementProposal] = {}
        self._load()

    def propose(self, title: str, reason: str, *, scope: str = "bug_fix") -> ImprovementProposal:
        normalized_scope = (scope or "bug_fix").strip().lower()
        if normalized_scope not in self.SAFE_SCOPES:
            raise ValueError(f"Unsafe improvement scope: {normalized_scope}")
        proposal = ImprovementProposal(
            proposal_id=uuid.uuid4().hex[:12],
            title=redact_secrets(
                (title or "Unnamed improvement").strip()
            )[:160],
            reason=redact_secrets(
                (reason or "No reason supplied").strip()
            )[:500],
            scope=normalized_scope,
            created_at=time.time(),
        )
        self._proposals[proposal.proposal_id] = proposal
        self._save()
        return proposal

    def list_proposals(self, *, limit: int = 10) -> list[ImprovementProposal]:
        return list(self._proposals.values())[-max(1, int(limit)) :][::-1]

    def prepare_worktree(self, proposal_id: str) -> ImprovementProposal:
        proposal = self._get(proposal_id)
        if proposal.status not in {"proposed", "rejected"}:
            return proposal
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        path = self.worktree_root / proposal.proposal_id
        result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(path), "HEAD"],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "worktree failed").strip()[:300])
        proposal.worktree = str(path)
        proposal.status = "testing"
        self._save()
        return proposal

    def test_worktree(self, proposal_id: str) -> ImprovementProposal:
        proposal = self._get(proposal_id)
        if proposal.status != "testing" or not proposal.worktree:
            raise RuntimeError("Proposal must have a prepared worktree")
        worktree = Path(proposal.worktree)
        command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-q",
        ]
        result = subprocess.run(
            command,
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=300,
        )
        proposal.test_output = (result.stdout or result.stderr or "").strip()[-2000:]
        proposal.status = "tested" if result.returncode == 0 else "proposed"
        self._save()
        return proposal

    def approve(self, proposal_id: str) -> ImprovementProposal:
        proposal = self._get(proposal_id)
        if proposal.status != "tested":
            raise RuntimeError("Only a successfully tested proposal can be approved")
        proposal.status = "approved"
        self._save()
        return proposal

    def status_speech(self) -> str:
        proposals = self.list_proposals(limit=3)
        if not proposals:
            return "No self-improvement proposals are waiting."
        parts = [f"{p.proposal_id}: {p.title} ({p.status})" for p in proposals]
        return "Self-improvement queue: " + "; ".join(parts)

    def _get(self, proposal_id: str) -> ImprovementProposal:
        proposal = self._proposals.get((proposal_id or "").strip())
        if proposal is None:
            raise KeyError(f"Improvement proposal not found: {proposal_id}")
        return proposal

    def _load(self) -> None:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                self._proposals = {
                    str(item["proposal_id"]): ImprovementProposal(**item)
                    for item in raw
                    if isinstance(item, dict) and item.get("proposal_id")
                }
        except (OSError, ValueError, TypeError, KeyError):
            self._proposals = {}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        payload = [asdict(p) for p in self._proposals.values()]
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.state_path)
