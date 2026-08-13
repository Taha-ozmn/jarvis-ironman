"""JARVIS verbal acknowledgements — Iron Man butler style."""

from __future__ import annotations

import random
import re


class JarvisNarrator:
    """Instant British-butler phrases while JARVIS works."""

    GENERIC_ACKS = (
        "Right away, sir.",
        "On it, sir.",
        "Very good, sir.",
        "At your service, sir.",
        "Immediately, sir.",
        "As you wish, sir.",
        "One moment, sir.",
        "Certainly, sir.",
        "Understood, sir.",
        "Allow me a moment, sir.",
    )

    WORK_UPDATES = (
        "One moment, sir.",
        "Still on it, sir.",
        "Working on that now, sir.",
        "Nearly there, sir.",
        "Just a moment more, sir.",
        "Running diagnostics, sir.",
        "Building that for you, sir.",
        "Still executing your directive, sir.",
        "Complex task in progress, sir.",
        "Continuing work — won't be long, sir.",
    )

    BOOT_LINES = (
        "Boot sequence initiated.",
        "Loading neural core.",
        "Connecting to Stark OS.",
        "Calibrating voice interface.",
        "All systems nominal.",
    )

    def instant_ack(self, command: str) -> str:
        """Brief acknowledgement while the AI processes — no keyword assumptions."""
        return random.choice(self.GENERIC_ACKS)

    def work_update(self, index: int = 0) -> str:
        return self.WORK_UPDATES[index % len(self.WORK_UPDATES)]

    def boot_line(self, index: int) -> str:
        return self.BOOT_LINES[index % len(self.BOOT_LINES)]

    @staticmethod
    def time_greeting(language: str = "en") -> str:
        import datetime

        hour = datetime.datetime.now().hour
        if str(language).lower().startswith("tr"):
            if hour < 12:
                return "Günaydın, efendim."
            if hour < 18:
                return "İyi günler, efendim."
            return "İyi akşamlar, efendim."
        if hour < 12:
            return "Good morning, sir."
        if hour < 18:
            return "Good afternoon, sir."
        return "Good evening, sir."

    @staticmethod
    def first_sentence(text: str) -> str:
        text = re.sub(r"\s+", " ", text.strip())
        if not text:
            return ""
        match = re.search(r"^(.+?[.!?])(?:\s|$)", text)
        if match and len(match.group(1)) >= 12:
            return match.group(1).strip()
        if len(text) > 80:
            return text[:80].rsplit(" ", 1)[0] + "…"
        return text

    @staticmethod
    def should_speak_more(preview: str, full: str) -> bool:
        if not full or not preview:
            return bool(full)
        preview_norm = preview.lower().strip(".,!? ")
        full_norm = full.lower().strip(".,!? ")
        if full_norm == preview_norm:
            return False
        if full_norm.startswith(preview_norm) and len(full) - len(preview) < 25:
            return False
        return True
