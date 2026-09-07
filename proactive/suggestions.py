"""Contextual proactive suggestions — second-brain nudges."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class Suggestion:
    voice: str
    detail: str = ""
    priority: int = 1  # 1 low .. 5 urgent


class SuggestionEngine:
    """Generate short proactive suggestions from local state (no LLM)."""

    def __init__(
        self,
        tasks: Any,
        briefing: Any,
        *,
        user_name: str = "",
        language: str = "en-GB",
    ) -> None:
        self.tasks = tasks
        self.briefing = briefing
        self.user_name = (user_name or "").strip()
        self.language = "en" if not str(language).lower().startswith("tr") else "tr"

    def generate(
        self,
        *,
        last_command: str = "",
        has_checkpoint: bool = False,
        checkpoint_summary: str = "",
    ) -> Suggestion:
        hour = datetime.now(timezone.utc).astimezone().hour
        pending = self.tasks.list(status="pending", limit=10)
        in_progress = self.tasks.list(status="in_progress", limit=5)
        briefing = self.briefing.generate()
        open_count = len(pending) + len(in_progress)

        if has_checkpoint and checkpoint_summary:
            if self.language == "tr":
                return Suggestion(
                    voice=(
                        f"Yarım kalan bir plan var: {checkpoint_summary}. "
                        "«devam et» dersen kaldığımız yerden sürdürürüm."
                    ),
                    detail=checkpoint_summary,
                    priority=4,
                )
            return Suggestion(
                voice=(
                    f"You have a paused plan: {checkpoint_summary}. "
                    "Say «continue» to resume where we left off."
                ),
                detail=checkpoint_summary,
                priority=4,
            )

        if open_count == 0:
            if 5 <= hour < 12:
                voice = (
                    "Good morning. No open tasks — shall I run a briefing or review a project?"
                    if self.language != "tr"
                    else "Günaydın. Açık görev yok — brifing veya proje incelemesi ister misiniz?"
                )
            elif 12 <= hour < 18:
                voice = (
                    "Afternoon clear. Want a status check or to pick up a project?"
                    if self.language != "tr"
                    else "Öğleden sonra sakin. Durum kontrolü veya bir projeye devam edelim mi?"
                )
            else:
                voice = (
                    "Evening — systems nominal. Anything you'd like me to organize?"
                    if self.language != "tr"
                    else "Akşam — sistemler hazır. Düzenlememi istediğiniz bir şey var mı?"
                )
            return Suggestion(voice=voice, detail=briefing.detail, priority=2)

        top = (in_progress[0].title if in_progress else pending[0].title) if (in_progress or pending) else ""
        if self.language == "tr":
            voice = (
                f"{open_count} açık görev var"
                + (f"; öncelik: «{top}»" if top else "")
                + ". «görevleri listele» veya «brifing» diyebilirsiniz."
            )
        else:
            voice = (
                f"You have {open_count} open task(s)"
                + (f"; top priority: «{top}»" if top else "")
                + ". Try «list tasks» or «daily briefing»."
            )
        if last_command and len(last_command) > 12:
            voice += (
                f" Last command was about: {last_command[:60]}…"
                if self.language != "tr"
                else f" Son komut: {last_command[:60]}…"
            )
        return Suggestion(voice=voice, detail=briefing.detail, priority=3)
