"""Local speaker enrollment and verification for voice command gating.

The verifier stores only a normalized acoustic profile. Raw recordings are
consumed in memory and are never persisted by this module.
"""

from __future__ import annotations

import io
import json
import math
import os
import struct
import tempfile
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


PROFILE_VERSION = 1
DEFAULT_THRESHOLD = 0.88
DEFAULT_MIN_VOICED_FRAMES = 8
FRAME_SIZE = 400
FRAME_HOP = 160


@dataclass(frozen=True)
class VerificationResult:
    """Result of checking one captured recording against the profile."""

    accepted: bool
    score: float
    reason: str


class SpeakerProfileError(ValueError):
    """Raised when an enrollment recording cannot produce a valid profile."""


def _normalize(values: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-12:
        raise SpeakerProfileError("Acoustic profile is empty")
    return [value / norm for value in values]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    return sum(a * b for a, b in zip(left, right))


def _read_pcm16(wav_bytes: bytes) -> tuple[int, list[float]]:
    """Read a mono or multi-channel PCM16 WAV into normalized mono samples."""

    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            raw = source.readframes(source.getnframes())
    except (EOFError, wave.Error) as err:
        raise SpeakerProfileError("Invalid WAV recording") from err

    if sample_width != 2 or channels < 1 or sample_rate < 8_000:
        raise SpeakerProfileError("Only PCM16 WAV recordings are supported")
    if len(raw) % 2:
        raise SpeakerProfileError("Corrupt PCM16 WAV recording")

    values = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    if channels == 1:
        samples = [value / 32768.0 for value in values]
    else:
        samples = [
            sum(values[index : index + channels]) / (32768.0 * channels)
            for index in range(0, len(values), channels)
        ]
    return sample_rate, samples


def _goertzel_power(frame: Sequence[float], sample_rate: int, frequency: float) -> float:
    """Estimate energy around one frequency without a third-party FFT."""

    if frequency >= sample_rate / 2:
        return 0.0
    coefficient = 2.0 * math.cos(2.0 * math.pi * frequency / sample_rate)
    previous = 0.0
    previous_previous = 0.0
    for sample in frame:
        current = sample + coefficient * previous - previous_previous
        previous_previous, previous = previous, current
    power = (
        previous_previous * previous_previous
        + previous * previous
        - coefficient * previous * previous_previous
    )
    return max(0.0, power)


def _frame_features(frame: Sequence[float], sample_rate: int) -> list[float]:
    """Extract compact voice characteristics from one voiced frame."""

    if not frame:
        return []
    mean = sum(frame) / len(frame)
    centered = [sample - mean for sample in frame]
    energy = sum(sample * sample for sample in centered) / len(centered)
    if energy <= 1e-10:
        return []

    zero_crossings = sum(
        1
        for left, right in zip(centered, centered[1:])
        if (left >= 0) != (right >= 0)
    )
    zcr = zero_crossings / len(centered)
    min_lag = max(2, int(sample_rate / 350))
    max_lag = min(len(centered) - 2, int(sample_rate / 70))
    best_lag = 0
    best_correlation = 0.0
    reference_energy = sum(sample * sample for sample in centered) or 1.0
    for lag in range(min_lag, max_lag + 1):
        correlation = sum(
            centered[index] * centered[index + lag]
            for index in range(len(centered) - lag)
        ) / reference_energy
        if correlation > best_correlation:
            best_lag = lag
            best_correlation = correlation
    pitch = sample_rate / best_lag if best_lag and best_correlation > 0.25 else 0.0
    frequencies = (350.0, 700.0, 1_400.0, 2_800.0, 5_600.0)
    band_powers = [
        _goertzel_power(centered, sample_rate, frequency)
        for frequency in frequencies
    ]
    total_power = sum(band_powers) or 1.0
    band_ratios = [math.log1p(power / total_power) for power in band_powers]
    return [
        (zcr - 0.08) / 0.08,
        (math.log1p(energy * 10_000.0) - 0.4) / 0.4,
        (pitch - 210.0) / 140.0,
        *[(ratio - 0.12) / 0.12 for ratio in band_ratios],
    ]


def acoustic_embedding(
    wav_bytes: bytes,
    min_voiced_frames: int = DEFAULT_MIN_VOICED_FRAMES,
) -> list[float]:
    """Build a deterministic local acoustic embedding from a WAV recording."""

    sample_rate, samples = _read_pcm16(wav_bytes)
    if len(samples) < FRAME_SIZE:
        raise SpeakerProfileError("Recording is too short")

    rms_values = [
        math.sqrt(
            sum(sample * sample for sample in samples[start : start + FRAME_SIZE])
            / FRAME_SIZE
        )
        for start in range(0, len(samples) - FRAME_SIZE + 1, FRAME_HOP)
    ]
    peak_rms = max(rms_values, default=0.0)
    voice_floor = max(0.005, peak_rms * 0.12)
    features = []
    for index, rms in enumerate(rms_values):
        if rms < voice_floor:
            continue
        start = index * FRAME_HOP
        extracted = _frame_features(
            samples[start : start + FRAME_SIZE],
            sample_rate,
        )
        if extracted:
            features.append(extracted)

    if len(features) < min_voiced_frames:
        raise SpeakerProfileError("Recording contains too little clear speech")

    means = [
        sum(row[index] for row in features) / len(features)
        for index in range(len(features[0]))
    ]
    deviations = [
        math.sqrt(
            sum((row[index] - means[index]) ** 2 for row in features)
            / len(features)
        )
        for index in range(len(features[0]))
    ]
    voiced_ratio = min(1.0, len(features) / max(1, len(rms_values)))
    return _normalize([*means, *deviations, voiced_ratio])


class SpeakerProfileStore:
    """Persist only the local embedding with owner-readable permissions."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    def load(self) -> list[float] | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            embedding = data.get("embedding")
            if data.get("version") != PROFILE_VERSION or not isinstance(embedding, list):
                return None
            values = [float(value) for value in embedding]
            if not values or any(not math.isfinite(value) for value in values):
                return None
            return _normalize(values)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def save(self, embedding: Sequence[float], sample_count: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": PROFILE_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sample_count": int(sample_count),
            "embedding": list(_normalize(embedding)),
        }
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
            text=True,
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                json.dump(payload, target, ensure_ascii=False)
                target.write("\n")
            os.replace(temporary_name, self.path)
            os.chmod(self.path, 0o600)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


class SpeakerVerifier:
    """Fail-closed local speaker verifier used before speech recognition."""

    def __init__(
        self,
        profile_path: Path,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        min_voiced_frames: int = DEFAULT_MIN_VOICED_FRAMES,
        require_profile: bool = True,
    ) -> None:
        self.store = SpeakerProfileStore(profile_path)
        self.threshold = max(-1.0, min(1.0, float(threshold)))
        self.min_voiced_frames = max(1, int(min_voiced_frames))
        self.require_profile = bool(require_profile)

    @property
    def enrolled(self) -> bool:
        return self.store.load() is not None

    def enroll(self, recordings: Iterable[bytes]) -> int:
        embeddings = [
            acoustic_embedding(recording, self.min_voiced_frames)
            for recording in recordings
        ]
        if not embeddings:
            raise SpeakerProfileError("No enrollment recordings were supplied")
        width = len(embeddings[0])
        if any(len(embedding) != width for embedding in embeddings):
            raise SpeakerProfileError("Enrollment recordings have incompatible profiles")
        centroid = [
            sum(embedding[index] for embedding in embeddings) / len(embeddings)
            for index in range(width)
        ]
        self.store.save(centroid, len(embeddings))
        return len(embeddings)

    def verify_bytes(self, wav_bytes: bytes) -> VerificationResult:
        profile = self.store.load()
        if profile is None:
            reason = "profile_missing" if self.require_profile else "profile_disabled"
            return VerificationResult(not self.require_profile, 0.0, reason)
        try:
            candidate = acoustic_embedding(wav_bytes, self.min_voiced_frames)
        except SpeakerProfileError as err:
            return VerificationResult(False, 0.0, str(err))
        score = _cosine(profile, candidate)
        return VerificationResult(
            score >= self.threshold,
            score,
            "accepted" if score >= self.threshold else "speaker_mismatch",
        )

    def verify_file(self, path: Path) -> VerificationResult:
        try:
            return self.verify_bytes(path.read_bytes())
        except OSError as err:
            return VerificationResult(False, 0.0, f"recording_unreadable: {err}")
