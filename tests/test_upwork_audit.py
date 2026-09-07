"""Upwork profile auditor tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from upwork.auditor import UpworkAuditor, audit_profile

SNAPSHOT = {
    "profile_url": "https://www.upwork.com/freelancers/~test",
    "name": "Taha Emre O.",
    "title": "Computer Engineering | Full Stack |",
    "hourly_rate_usd": 15.0,
    "profile_completion_pct": 90,
    "availability_badge": "off",
    "boost_profile": "off",
    "overview_excerpt": "Computer engineering student. Swift Flutter React cybersecurity.",
    "skills_visible": ["Mobile App", "App Development"],
    "market_signals": [{"job": "Swift iOS", "level": "Expert", "budget_hr": 35}],
}


class UpworkAuditorTests(unittest.TestCase):
    def test_audit_finds_critical_gaps(self) -> None:
        report = UpworkAuditor(SNAPSHOT).run()
        self.assertLess(report.overall_score, 80)
        self.assertEqual(report.positioning, "ios_mobile")
        areas = {f.area for f in report.findings}
        self.assertIn("Availability", areas)
        self.assertIn("Portfolio", areas)
        self.assertTrue(report.headline_options)
        self.assertTrue(report.skills_to_add)

    def test_audit_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "snap.json"
            out = Path(tmp) / "report.json"
            snap.write_text(json.dumps(SNAPSHOT), encoding="utf-8")
            report = audit_profile(snap, output_path=out)
            self.assertTrue(out.exists())
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["name"], report.name)


if __name__ == "__main__":
    unittest.main()
