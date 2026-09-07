#!/usr/bin/env python3
"""Run Upwork profile audit and print actionable report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from upwork.auditor import audit_profile, load_snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Upwork profile from snapshot JSON")
    parser.add_argument(
        "--snapshot",
        default=str(ROOT / "data" / "upwork" / "profile_snapshot.json"),
        help="Path to profile snapshot JSON",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "data" / "upwork" / "audit_report.json"),
        help="Write structured audit report here",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON to stdout")
    args = parser.parse_args(argv)

    report = audit_profile(args.snapshot, output_path=args.out)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return 0

    print(f"\n=== Upwork Audit: {report.name} ===")
    print(f"Score: {report.overall_score}/100  |  Completion: {report.completion_pct}%")
    print(f"Recommended niche: {report.positioning.replace('_', ' ')}")
    print(f"Report saved: {args.out}\n")

    print("--- Critical findings ---")
    for f in report.findings:
        if f.severity in ("critical", "high"):
            print(f"• [{f.severity.upper()}] {f.area}: {f.issue}")
            print(f"  → {f.action}\n")

    print("--- Quick wins (do today) ---")
    for i, w in enumerate(report.quick_wins, 1):
        print(f"{i}. {w}")

    print("\n--- Suggested headline ---")
    print(report.headline_options[0])

    print("\n--- Rate ---")
    rr = report.rate_recommendation
    lo, hi = rr.get("recommended_range_usd", [22, 26])
    print(f"Current ${rr.get('current_usd')}/hr → recommend ${lo}–${hi}/hr")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
