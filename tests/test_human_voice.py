"""Human-like TTS helpers — SSML breaks, phrase split, filler strip."""

from __future__ import annotations

import unittest

from voice.narrator import JarvisNarrator
from voice.speaker import DEFAULT_PITCH, DEFAULT_RATE
from voice.speech_clean import (
    speak_safe_tr,
    split_speech_phrases,
    strip_robotic_filler,
    tts_inner_ssml,
)


class RoboticFillerTests(unittest.TestCase):
    def test_strips_bakiyorum_spam(self) -> None:
        self.assertEqual(strip_robotic_filler("Bakıyorum."), "")
        self.assertEqual(strip_robotic_filler("Hemen bakıyorum."), "")
        self.assertEqual(
            strip_robotic_filler("Bakıyorum. Chrome açıldı."),
            "Chrome açıldı.",
        )

    def test_speak_safe_strips_filler_and_efendim(self) -> None:
        self.assertEqual(speak_safe_tr("Bakıyorum, efendim."), "")
        self.assertIn("açılamadı", speak_safe_tr("Could not open Chrome"))

    def test_keeps_real_content(self) -> None:
        msg = "Takvimde iki toplantı var."
        self.assertEqual(speak_safe_tr(msg), msg)


class PhraseSplitTests(unittest.TestCase):
    def test_short_stays_one(self) -> None:
        self.assertEqual(split_speech_phrases("Hazırım."), ["Hazırım."])

    def test_splits_sentences_without_tiny_tails(self) -> None:
        text = "Günaydın. Sistemler hazır. Size nasıl yardımcı olayım?"
        parts = split_speech_phrases(text)
        self.assertGreaterEqual(len(parts), 2)
        self.assertLessEqual(len(parts), 4)
        self.assertTrue(all(p.strip() for p in parts))

    def test_caps_chunk_count(self) -> None:
        text = " ".join(f"Cümle {i} bitti." for i in range(12))
        parts = split_speech_phrases(text, max_chunk=40, max_chunks=4)
        self.assertLessEqual(len(parts), 4)


class SsmlInnerTests(unittest.TestCase):
    def test_inserts_breaks_and_escapes(self) -> None:
        inner = tts_inner_ssml("Merhaba, Taha & ekip. Hazırım.")
        self.assertIn('<break time="160ms"/>', inner)
        self.assertIn('<break time="320ms"/>', inner)
        self.assertIn("&amp;", inner)
        self.assertNotIn("<speak", inner)

    def test_empty(self) -> None:
        self.assertEqual(tts_inner_ssml(""), "")


class NarratorProfessionalTests(unittest.TestCase):
    def test_no_bakiyorum_or_efendim(self) -> None:
        n = JarvisNarrator()
        blob = " ".join(n.GENERIC_ACKS + n.WORK_UPDATES + n.BOOT_LINES).lower()
        self.assertNotIn("bakıyorum", blob)
        self.assertNotIn("efendim", blob)
        self.assertNotIn("emrinizdeyim", blob)

    def test_defaults_are_ryan_human_pace(self) -> None:
        from voice.speaker import DEFAULT_ENGLISH_VOICE

        self.assertEqual(DEFAULT_ENGLISH_VOICE, "en-GB-RyanNeural")
        self.assertEqual(DEFAULT_RATE, "-10%")
        self.assertEqual(DEFAULT_PITCH, "-4Hz")


if __name__ == "__main__":
    unittest.main()
