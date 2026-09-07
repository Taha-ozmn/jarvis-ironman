import io
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

from security.speaker_verification import SpeakerVerifier, VerificationResult
from voice.listener import VoiceListener


def make_tone_wav(frequency: float, harmonic: float = 2.0) -> bytes:
    sample_rate = 16_000
    raw = []
    for index in range(int(sample_rate * 1.2)):
        time_value = index / sample_rate
        envelope = min(1.0, index / 8_000, (sample_rate * 1.2 - index) / 8_000)
        value = envelope * (
            0.22 * math.sin(2 * math.pi * frequency * time_value)
            + 0.08 * math.sin(2 * math.pi * frequency * harmonic * time_value)
        )
        raw.append(struct.pack("<h", int(value * 32767)))
    output = io.BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(sample_rate)
        recording.writeframes(b"".join(raw))
    return output.getvalue()


class SpeakerVerificationTests(unittest.TestCase):
    def test_missing_profile_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            verifier = SpeakerVerifier(Path(directory) / "profile.json")
            result = verifier.verify_bytes(make_tone_wav(180))
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "profile_missing")

    def test_enrollment_accepts_owner_and_rejects_different_voice(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.json"
            verifier = SpeakerVerifier(profile)
            owner = make_tone_wav(180)
            verifier.enroll([owner, owner, owner])

            owner_result = verifier.verify_bytes(owner)
            other_result = verifier.verify_bytes(make_tone_wav(800))
            profile_mode = profile.stat().st_mode & 0o777

        self.assertTrue(owner_result.accepted)
        self.assertFalse(other_result.accepted)
        self.assertEqual(profile_mode, 0o600)

    def test_profile_does_not_store_raw_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.json"
            recording = make_tone_wav(180)
            SpeakerVerifier(profile).enroll([recording] * 3)
            contents = profile.read_text(encoding="utf-8")
        self.assertNotIn("RIFF", contents)
        self.assertNotIn("WAVE", contents)

    def test_rejected_recording_never_reaches_stt(self):
        with tempfile.NamedTemporaryFile(suffix=".wav") as recording:
            recording.write(make_tone_wav(800))
            recording.flush()
            verifier = Mock()
            verifier.verify_file.return_value = VerificationResult(
                False,
                0.2,
                "speaker_mismatch",
            )
            listener = VoiceListener.__new__(VoiceListener)
            listener.speaker_verifier = verifier
            listener.on_voice_rejected = Mock()

            with patch("speech_recognition.Recognizer.recognize_google") as recognize:
                result = listener._recognize_wav(Path(recording.name))

        self.assertIsNone(result)
        recognize.assert_not_called()
        listener.on_voice_rejected.assert_called_once_with("speaker_mismatch")

    def test_bilingual_candidate_selection_prefers_matching_language_markers(self):
        turkish = ("tr-TR", "jarvis ekranımı gör", 0.0)
        turkish_noise = ("tr-TR", "jarvis anlamsız kelimeler", 0.0)
        self.assertGreater(
            VoiceListener._candidate_score(turkish),
            VoiceListener._candidate_score(turkish_noise),
        )
        english = ("en-US", "jarvis open my screen", 0.0)
        self.assertGreater(
            VoiceListener._candidate_score(english),
            VoiceListener._candidate_score(("tr-TR", "jarvis open my screen", 0.0)),
        )


if __name__ == "__main__":
    unittest.main()
