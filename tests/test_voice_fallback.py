"""Edge TTS failure must still speak via native macOS say."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from voice.speaker import VoiceSpeaker


class EdgeFallbackTests(unittest.TestCase):
    def test_edge_failure_falls_back_to_native(self) -> None:
        speaker = VoiceSpeaker(
            engine="jarvis",
            native_first=False,
            cinematic=True,
            language="en-GB",
        )
        speaker._ready.set()
        speaker._loop = asyncio.new_event_loop()

        with patch.object(
            speaker,
            "_synthesize_edge",
            new=AsyncMock(side_effect=RuntimeError("edge offline")),
        ), patch.object(speaker, "_notify_edge_fallback") as notify, patch.object(
            speaker, "_speak_native"
        ) as native:
            asyncio.run(speaker._speak_phrase_async("Standing by, Taha."))

        notify.assert_called_once()
        native.assert_called_once_with("Standing by, Taha.")


if __name__ == "__main__":
    unittest.main()
