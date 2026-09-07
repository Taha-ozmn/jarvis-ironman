"""Upwork profile audit tool for JARVIS."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult
from upwork.auditor import audit_profile, load_snapshot

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "data" / "upwork" / "profile_snapshot.json"
DEFAULT_REPORT = ROOT / "data" / "upwork" / "audit_report.json"


class UpworkAuditTool(BaseTool):
    name = "upwork.audit_profile"
    description = (
        "Audit Upwork freelancer profile from snapshot JSON — scores gaps, "
        "suggests headline, skills, rate, and weekly plan"
    )
    permission_level = PermissionLevel.LOCAL
    input_schema = {
        "snapshot_path": {"type": "str", "required": False},
        "refresh_from_url": {"type": "bool", "required": False},
    }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        snap_path = str(arguments.get("snapshot_path") or DEFAULT_SNAPSHOT)
        try:
            report = audit_profile(snap_path, output_path=DEFAULT_REPORT)
        except FileNotFoundError:
            return ToolResult(
                ok=False,
                error=f"Snapshot not found: {snap_path}. Capture profile first.",
            )
        except json.JSONDecodeError as err:
            return ToolResult(ok=False, error=f"Invalid snapshot JSON: {err}")

        top = report.findings[:3]
        summary = (
            f"Upwork audit for {report.name}: score {report.overall_score}/100, "
            f"{report.completion_pct}% complete. "
            f"Focus: {report.positioning.replace('_', ' ')}. "
            f"Top actions: "
            + "; ".join(f.action for f in top)
            + f". Report: {DEFAULT_REPORT}"
        )
        return ToolResult(ok=True, data=summary, meta=report.to_dict())
