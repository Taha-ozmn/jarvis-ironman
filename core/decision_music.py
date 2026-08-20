"""Autonomous music decision — vague requests become a concrete play choice.

This is the seed of JARVIS decision-making: interpret → decide → act → explain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_FILLERS = frozenset(
    {
        "güzel",
        "guzel",
        "bir",
        "şarkı",
        "sarki",
        "şarkisi",
        "sarkisi",
        "müzik",
        "muzik",
        "müziği",
        "muzigi",
        "şey",
        "sey",
        "bisey",
        "birşey",
        "birsey",
        "nice",
        "good",
        "random",
        "any",
        "something",
        "bana",
        "lütfen",
        "lutfen",
        "please",
        "song",
        "music",
        "track",
        "aç",
        "ac",
        "çal",
        "cal",
        "play",
        "dinle",
    }
)

# Mood / vibe → concrete searchable track (autonomous pick)
_MOOD_PICKS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(r"güzel|guzel|nice|güzel bir", re.I),
        "Teoman Güzel Bir Gün official",
        "Teoman — Güzel Bir Gün",
    ),
    (
        re.compile(r"huzur|sakin|calm|relax|lofi|lo-fi", re.I),
        "lofi hip hop radio beats to relax study to",
        "a lo-fi focus mix",
    ),
    (
        re.compile(r"yeni|new|recent|güncel|guncel|latest|chart|hit|çıkan|cikan", re.I),
        "2025 new music hits official",
        "recent chart hits",
    ),
    (
        re.compile(r"enerji|energy|rock|hızlı|hizli", re.I),
        "AC/DC Back in Black official",
        "AC/DC — Back in Black",
    ),
    (
        re.compile(r"hüzün|huzun|üzgün|uzgun|sad", re.I),
        "Sezen Aksu Gidiyorum official",
        "Sezen Aksu — Gidiyorum",
    ),
    (
        re.compile(r"türkçe|turkce|turkish", re.I),
        "Tarkan Şımarık official",
        "Tarkan — Şımarık",
    ),
)

_INTENT_ONLY = frozenset(
    {
        "yeni",
        "eski",
        "daha",
        "şarkı",
        "sarki",
        "şarkılar",
        "sarkilar",
        "şarkılardan",
        "sarkilardan",
        "müzik",
        "muzik",
        "new",
        "songs",
        "music",
        "recent",
        "latest",
        "güncel",
        "guncel",
        "hit",
        "hits",
        "chart",
        "çıkan",
        "cikan",
        "sakin",
        "huzur",
        "calm",
        "relax",
        "enerji",
        "energy",
        "hüzün",
        "huzun",
        "güzel",
        "guzel",
    }
)

_DEFAULT_PICK = (
    "lofi hip hop radio beats to relax study to",
    "a lo-fi focus mix",
)


@dataclass(frozen=True)
class MusicDecision:
    """Concrete play decision after reasoning over a vague or specific request."""

    search_query: str
    display_name: str
    autonomous: bool
    rationale: str


def is_vague_music_query(query: str) -> bool:
    words = re.findall(r"[\wğüşıöçĞÜŞİÖÇ]+", (query or "").lower())
    if not words:
        return True
    meaningful = [w for w in words if w not in _FILLERS and len(w) > 1]
    if not meaningful:
        return True
    # Single weak adjective left after stripping "şarkı"
    if len(meaningful) == 1 and meaningful[0] in {
        "güzel",
        "guzel",
        "nice",
        "good",
        "yeni",
        "eski",
    }:
        return True
    return len((query or "").strip()) < 4


def _is_intent_only_query(query: str) -> bool:
    """True when the query is mood/intent words only — no concrete artist or track."""
    words = re.findall(r"[\wğüşıöçĞÜŞİÖÇ]+", (query or "").lower())
    meaningful = [w for w in words if w not in _FILLERS and len(w) > 1]
    return bool(meaningful) and all(w in _INTENT_ONLY for w in meaningful)


def decide_music_play(raw_query: str) -> MusicDecision:
    """Interpret user music intent and decide what to actually play."""
    q = (raw_query or "").strip()
    blob = q.lower()
    treat_as_open = is_vague_music_query(q) or _is_intent_only_query(q)

    if treat_as_open:
        for pattern, search, display in _MOOD_PICKS:
            if pattern.search(blob) or pattern.search(q):
                return MusicDecision(
                    search_query=search,
                    display_name=display,
                    autonomous=True,
                    rationale=(
                        f"You didn't name a specific track — I picked {display}."
                    ),
                )

        search, display = _DEFAULT_PICK
        return MusicDecision(
            search_query=search,
            display_name=display,
            autonomous=True,
            rationale=(
                f"No artist specified — I chose {display}. "
                "Say an artist name anytime and I'll switch."
            ),
        )

    return MusicDecision(
        search_query=q,
        display_name=q,
        autonomous=False,
        rationale="Playing the track you named.",
    )
