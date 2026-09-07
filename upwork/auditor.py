"""Upwork profile auditor — scores gaps and generates actionable improvements."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "data" / "upwork" / "profile_snapshot.json"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


@dataclass
class Finding:
    area: str
    severity: str  # critical | high | medium | low
    issue: str
    action: str
    impact: str


@dataclass
class AuditReport:
    profile_url: str
    name: str
    overall_score: int
    completion_pct: int
    positioning: str
    findings: list[Finding] = field(default_factory=list)
    quick_wins: list[str] = field(default_factory=list)
    headline_options: list[str] = field(default_factory=list)
    overview_draft: str = ""
    skills_to_add: list[str] = field(default_factory=list)
    portfolio_ideas: list[str] = field(default_factory=list)
    rate_recommendation: dict[str, Any] = field(default_factory=dict)
    weekly_plan: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["findings"] = [asdict(f) for f in self.findings]
        return data


class UpworkAuditor:
    """Rule-based profile audit from a structured snapshot."""

    GENERIC_SKILLS = {
        "mobile app",
        "app development",
        "desktop application",
        "android app development",
        "ios development",
    }

    STRONG_SKILLS = {
        "swift",
        "swiftui",
        "uikit",
        "flutter",
        "react",
        "react native",
        "python",
        "javascript",
        "typescript",
        "node.js",
        "firebase",
        "rest api",
        "git",
        "cybersecurity",
        "penetration testing",
    }

    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = snapshot

    def run(self) -> AuditReport:
        s = self.snapshot
        findings: list[Finding] = []
        score = 100

        completion = int(s.get("profile_completion_pct") or 0)
        if completion < 100:
            missing = s.get("missing_sections") or []
            labels = ", ".join(m["section"] for m in missing[:4])
            findings.append(
                Finding(
                    area="Completeness",
                    severity="critical",
                    issue=f"Profile is {completion}% complete.",
                    action=f"Add {labels} — Upwork weights these heavily in search.",
                    impact="Higher rank in client search; unlocks profile badges.",
                )
            )
            score -= max(0, 100 - completion) // 2

        if str(s.get("availability_badge", "")).lower() == "off":
            findings.append(
                Finding(
                    area="Availability",
                    severity="critical",
                    issue="Availability badge is OFF while profile says 30+ hrs/week.",
                    action="Turn on the availability badge in Profile settings today.",
                    impact="Clients filter for 'available now'; invisible otherwise.",
                )
            )
            score -= 12

        rate = float(s.get("hourly_rate_usd") or 0)
        market = s.get("market_signals") or []
        expert_rates = [
            float(j.get("budget_hr") or 0)
            for j in market
            if str(j.get("level", "")).lower() == "expert"
        ]
        target = max(expert_rates) if expert_rates else max(rate, 25.0)
        if rate < target * 0.6:
            findings.append(
                Finding(
                    area="Pricing",
                    severity="high",
                    issue=f"Rate ${rate:.0f}/hr undercuts Expert-tier matches (${target:.0f}/hr).",
                    action=f"Raise to ${max(22, int(target * 0.65))}-${int(target * 0.75)}/hr for iOS/Swift work.",
                    impact="Signals quality; filters low-budget clients.",
                )
            )
            score -= 10

        title = str(s.get("title") or "").strip()
        if title.endswith("|") or title.count("|") >= 2:
            findings.append(
                Finding(
                    area="Headline",
                    severity="high",
                    issue="Headline is broad and ends awkwardly ('|').",
                    action="Pick one niche headline — mobile OR security, not both in the title.",
                    impact="Clients scan titles in 2 seconds; clarity wins invites.",
                )
            )
            score -= 8

        skills = {str(x).strip().lower() for x in (s.get("skills_visible") or [])}
        if skills.issubset(self.GENERIC_SKILLS) or len(skills) < 8:
            findings.append(
                Finding(
                    area="Skills",
                    severity="high",
                    issue="Skills are generic; missing Swift, Flutter, React, API keywords.",
                    action="Add 10–15 specific stack tags matching your best jobs.",
                    impact="Upwork matches you to relevant job feeds.",
                )
            )
            score -= 10

        overview = str(s.get("overview_excerpt") or "").lower()
        if "student" in overview and "delivered" not in overview and "built" not in overview:
            findings.append(
                Finding(
                    area="Overview",
                    severity="medium",
                    issue="Bio leads with student status, not client outcomes.",
                    action="Open with 2 shipped apps or measurable results, then mention degree.",
                    impact="Clients hire outcomes, not enrolment.",
                )
            )
            score -= 6

        if "cybersecurity" in overview and "swift" in overview:
            findings.append(
                Finding(
                    area="Positioning",
                    severity="medium",
                    issue="Two competing niches: security vs mobile/full-stack.",
                    action="Run two profiles OR pick primary niche (recommend iOS/mobile).",
                    impact="Focused profiles convert 2–3× better on Upwork.",
                )
            )
            score -= 5

        if str(s.get("boost_profile", "")).lower() == "off":
            findings.append(
                Finding(
                    area="Visibility",
                    severity="medium",
                    issue="Profile Boost is off despite Freelancer Plus.",
                    action="Enable Boost on your top niche (Swift/iOS) when applying to 3+ jobs/week.",
                    impact="Extra impressions in client search.",
                )
            )
            score -= 4

        if not s.get("portfolio_count"):
            findings.append(
                Finding(
                    area="Portfolio",
                    severity="critical",
                    issue="No portfolio items visible (+20% completion).",
                    action="Add 3 case studies: JARVIS app, a Flutter/React project, one security lab.",
                    impact="Portfolio is the #1 trust signal for new freelancers.",
                )
            )
            score -= 15

        positioning = self._recommend_positioning(s)
        headline_options = self._headline_options(positioning)
        overview_draft = self._overview_draft(s, positioning)
        skills_to_add = self._skills_to_add(s, positioning)
        portfolio_ideas = self._portfolio_ideas(s)
        rate_rec = {
            "current_usd": rate,
            "recommended_range_usd": [
                max(22, int(target * 0.65)),
                int(target * 0.75),
            ],
            "niche": positioning,
            "rationale": "Aligned with Expert Swift matches in your job feed.",
        }
        quick_wins = [
            "Turn availability badge ON.",
            "Fix headline — remove trailing pipe, pick iOS/mobile focus.",
            "Add 10 specific skills (Swift, SwiftUI, Flutter, React, Python).",
            "Upload 30–45s intro video (phone is fine).",
            "Add 3 portfolio items with screenshots and results.",
        ]
        weekly_plan = [
            "Day 1: Availability ON, headline + overview rewrite, skills update.",
            "Day 2–3: Build 3 portfolio entries from GitHub/JARVIS/mobile work.",
            "Day 4: Record intro video; add education + employment entries.",
            "Day 5: Apply to 5 Expert Swift jobs with custom cover letters.",
            "Day 6–7: Raise rate to $22–26/hr after first interview invite.",
        ]

        return AuditReport(
            profile_url=str(s.get("profile_url") or ""),
            name=str(s.get("name") or ""),
            overall_score=max(0, min(100, score)),
            completion_pct=completion,
            positioning=positioning,
            findings=findings,
            quick_wins=quick_wins,
            headline_options=headline_options,
            overview_draft=overview_draft,
            skills_to_add=skills_to_add,
            portfolio_ideas=portfolio_ideas,
            rate_recommendation=rate_rec,
            weekly_plan=weekly_plan,
        )

    def _recommend_positioning(self, s: dict[str, Any]) -> str:
        market = s.get("market_signals") or []
        swift_jobs = sum(
            1
            for j in market
            if re.search(r"swift|ios", str(j.get("job", "")), re.I)
        )
        if swift_jobs >= 1:
            return "ios_mobile"
        overview = str(s.get("overview_excerpt") or "").lower()
        if "cybersecurity" in overview or "ethical hacking" in overview:
            return "security"
        return "full_stack_mobile"

    def _headline_options(self, positioning: str) -> list[str]:
        if positioning == "ios_mobile":
            return [
                "iOS & Swift Developer | SwiftUI, UIKit, MapKit | Ship App Store-ready apps",
                "Mobile Developer (iOS + Flutter) | Full-stack React backends | Tekirdag, TR",
                "Swift / iOS Engineer | MVVM, API integration, TestFlight delivery",
            ]
        if positioning == "security":
            return [
                "Cybersecurity Analyst | Pen testing, network hardening, OWASP | CEH-ready",
                "Ethical Hacker | Vulnerability assessment & secure mobile/web apps",
            ]
        return [
            "Full-Stack Developer | React, Flutter, Swift | Web + mobile delivery",
            "Computer Engineer | Desktop, mobile & web apps | Python + JavaScript",
        ]

    def _overview_draft(self, s: dict[str, Any], positioning: str) -> str:
        name = str(s.get("name") or "Taha").split()[0]
        if positioning == "ios_mobile":
            return (
                f"I build and ship iOS apps clients can publish — not prototypes that stall in TestFlight.\n\n"
                f"Recent focus: Swift, SwiftUI, UIKit, MapKit, REST APIs, and Flutter when cross-platform "
                f"makes sense. I work from Tekirdag with fluent English and clear async updates.\n\n"
                f"Computer Engineering (Amasya University, final year) — I combine solid CS fundamentals "
                f"with hands-on delivery: JARVIS-style automation tools, mobile clients, and full-stack "
                f"React backends.\n\n"
                f"If you need an iOS developer who communicates plainly and hits milestones, send a message "
                f"with your app idea and timeline."
            )
        return (
            f"I deliver working software — mobile, web, and desktop — with clean code and honest timelines.\n\n"
            f"Stack: Swift, Flutter, React, Python, REST APIs, Git. Based in Tekirdag; fluent English.\n\n"
            f"Final-year Computer Engineering student with production-side projects including voice AI "
            f"assistants and cross-platform apps. Tell me your scope and I'll propose a clear first milestone."
        )

    def _skills_to_add(self, s: dict[str, Any], positioning: str) -> list[str]:
        base = [
            "Swift",
            "SwiftUI",
            "UIKit",
            "iOS Development",
            "Flutter",
            "React",
            "JavaScript",
            "Python",
            "REST API",
            "Git",
            "Firebase",
            "Mobile App Development",
        ]
        if positioning == "ios_mobile":
            base.extend(["MapKit", "Core Data", "Xcode", "TestFlight", "App Store"])
        if positioning == "security":
            base.extend(
                ["Cybersecurity", "Penetration Testing", "Network Security", "OWASP"]
            )
        existing = {str(x).lower() for x in (s.get("skills_visible") or [])}
        return [sk for sk in base if sk.lower() not in existing]

    def _portfolio_ideas(self, s: dict[str, Any]) -> list[str]:
        return [
            "JARVIS Iron Man assistant — macOS voice AI, HUD, automation (screenshots + GitHub link).",
            "iOS/Swift app — MapKit or SwiftUI feature with before/after metrics.",
            "Flutter or React cross-platform client — auth, API, deployed build.",
            "Cybersecurity lab write-up — scoped pen test or hardening checklist (if keeping security niche).",
            "Convertio-style utility or desktop tool — shows breadth without diluting iOS focus.",
        ]


def load_snapshot(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_SNAPSHOT
    return json.loads(p.read_text(encoding="utf-8"))


def audit_profile(
    snapshot_path: Path | str | None = None,
    *,
    output_path: Path | str | None = None,
) -> AuditReport:
    snapshot = load_snapshot(snapshot_path)
    report = UpworkAuditor(snapshot).run()
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return report
