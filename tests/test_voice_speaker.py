"""Voice speaker — English Ryan default; Turkish voices available but not for replies."""

from __future__ import annotations

import asyncio
import unittest

from voice.speaker import (
    AHMET_VOICE,
    DEFAULT_ENGLISH_VOICE,
    DEFAULT_TURKISH_VOICE,
    format_edge_error,
    is_valid_edge_voice,
    list_turkish_voices,
    normalize_voice,
    resolve_edge_voice,
)


class VoiceNormalizationTests(unittest.TestCase):
    def test_turkish_aliases(self) -> None:
        self.assertEqual(DEFAULT_TURKISH_VOICE, "tr-TR-EmelNeural")
        self.assertEqual(normalize_voice("", "tr-TR"), DEFAULT_TURKISH_VOICE)
        self.assertEqual(normalize_voice("emel", "tr-TR"), DEFAULT_TURKISH_VOICE)
        self.assertEqual(normalize_voice("tr-emel", "tr-TR"), DEFAULT_TURKISH_VOICE)
        self.assertEqual(normalize_voice("ahmet", "tr-TR"), AHMET_VOICE)
        self.assertEqual(normalize_voice("TR-AhmetNeural", "tr-TR"), AHMET_VOICE)

    def test_english_defaults_to_ryan(self) -> None:
        self.assertEqual(DEFAULT_ENGLISH_VOICE, "en-GB-RyanNeural")
        self.assertEqual(normalize_voice("", "en-GB"), DEFAULT_ENGLISH_VOICE)
        self.assertEqual(normalize_voice("ryan", "en-GB"), DEFAULT_ENGLISH_VOICE)
        self.assertEqual(normalize_voice("en-GB-RyanNeural", "en-GB"), DEFAULT_ENGLISH_VOICE)

    def test_resolve_english_ryan_for_replies(self) -> None:
        self.assertEqual(resolve_edge_voice("en-GB"), DEFAULT_ENGLISH_VOICE)
        self.assertEqual(
            resolve_edge_voice("en-GB", english_voice="en-GB-ThomasNeural"),
            "en-GB-ThomasNeural",
        )
        self.assertEqual(resolve_edge_voice("tr-TR"), DEFAULT_TURKISH_VOICE)
        self.assertEqual(
            resolve_edge_voice("tr-TR", turkish_voice="tr-TR-EmelNeural"),
            "tr-TR-EmelNeural",
        )
        self.assertEqual(
            resolve_edge_voice("tr-TR", legacy_voice="tr-TR-AhmetNeural"),
            AHMET_VOICE,
        )

    def test_format_empty_timeout_error(self) -> None:
        msg = format_edge_error(asyncio.TimeoutError())
        self.assertTrue(msg)


class EdgeTtsCatalogTests(unittest.TestCase):
    def test_turkish_voices_in_catalog(self) -> None:
        try:
            names = asyncio.run(list_turkish_voices())
        except Exception as err:
            self.skipTest(f"edge-tts catalog unavailable: {err}")
        self.assertIn(DEFAULT_TURKISH_VOICE, names)
        self.assertIn(AHMET_VOICE, names)
        self.assertEqual(len(names), 2)

    def test_configured_voices_are_valid(self) -> None:
        for voice in (DEFAULT_TURKISH_VOICE, AHMET_VOICE, DEFAULT_ENGLISH_VOICE):
            with self.subTest(voice=voice):
                try:
                    ok = asyncio.run(is_valid_edge_voice(voice))
                except Exception as err:
                    self.skipTest(f"edge-tts catalog unavailable: {err}")
                self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
