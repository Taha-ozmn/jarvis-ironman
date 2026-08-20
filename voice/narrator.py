"""JARVIS verbal acknowledgements — classic film English, not parody."""

from __future__ import annotations

import random
import re


class JarvisNarrator:
    """Short English acknowledgements while JARVIS works — no chatbot filler."""

    # Deliberately no "Bakıyorum." — that cadence sounds like generic AI TTS.
    GENERIC_ACKS = (
        "Right away.",
        "Understood.",
        "On it.",
        "One moment.",
        "Certainly.",
    )

    WORK_UPDATES = (
        "Still working on that, sir.",
        "Hang on — still on it.",
        "Almost there.",
        "Thinking it through, sir.",
        "Working the next step now.",
        "Still on your request.",
    )

    BOOT_LINES = (
        "Systems coming online.",
        "Voice interface ready.",
        "Command centre online.",
        "At the ready.",
    )

    GENERIC_ACKS_TR = (
        "Tamam.",
        "Anlaşıldı.",
        "Hemen.",
        "Bir saniye.",
        "Tabii.",
    )

    WORK_UPDATES_TR = (
        "Hâlâ üzerinde çalışıyorum.",
        "Devam ediyorum.",
        "Neredeyse bitti.",
    )

    BOOT_LINES_TR = (
        "Sistemler yükleniyor.",
        "Ses arayüzü hazır.",
        "Komuta merkezi çevrimiçi.",
        "Hazırım.",
    )

    def instant_ack(self, command: str, *, language: str = "en") -> str:
        """Brief acknowledgement while the AI processes — English only for TTS."""
        del command, language
        return random.choice(self.GENERIC_ACKS)

    def work_update(self, index: int = 0, *, language: str = "en") -> str:
        del language
        return self.WORK_UPDATES[index % len(self.WORK_UPDATES)]

    def boot_line(self, index: int) -> str:
        return self.BOOT_LINES[index % len(self.BOOT_LINES)]

    @staticmethod
    def time_greeting(language: str = "en") -> str:
        import datetime

        del language
        hour = datetime.datetime.now().hour
        if hour < 12:
            return "Good morning."
        if hour < 18:
            return "Good afternoon."
        return "Good evening."

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
