"""Normalize spoken app names from Turkish/English open/close commands."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

# Common speech-to-text mishearings for app names.
SPEECH_APP_ALIASES = {
    "çift gp": "chrome",
    "cift gp": "chrome",
    "çift g p": "chrome",
    "google krom": "chrome",
    "google chrome": "chrome",
    "krom": "chrome",
    "spotifay": "spotify",
    "spotifi": "spotify",
    "termınal": "terminal",
    "terminal": "terminal",
    "kursor": "cursor",
    "purser": "cursor",
    "crusoe": "cursor",
    "cursur": "cursor",
    "cursorr": "cursor",
    "jours": "cursor",
    "jors": "cursor",
    "cursor": "cursor",
    "safariyi": "safari",
    "chromeyi": "chrome",
    "chrome'u": "chrome",
    "chrome u": "chrome",
    "notları": "notes",
    "notlari": "notes",
    "not defteri": "notes",
    "youtube": "youtube",
    "you tube": "youtube",
    "yt": "youtube",
    "gmail": "gmail",
    "g mail": "gmail",
    "google mail": "gmail",
    "googlemail": "gmail",
    "google mail hesabı": "gmail",
    "google mail hesabi": "gmail",
    "mail hesabı": "gmail",
    "mail hesabi": "gmail",
    "outlook": "outlook",
    "out look": "outlook",
    "hot mail": "hotmail",
    "hotmail": "hotmail",
    "youtubedan": "youtube",
    "youtube'dan": "youtube",
    "youtube dan": "youtube",
    "youtube video": "youtube",
    "youtube'dan video": "youtube",
    "youtubedan video": "youtube",
    "visual studio code": "vscode",
    "visual studio codeac": "vscode",
    "codeac": "vscode",
    "code": "vscode",
    "vscode": "vscode",
    "v s code": "vscode",
    "github": "github",
    "git hub": "github",
    "githuub": "github",
    "githab": "github",
}

# Sites opened via URL (not macOS app bundle).
SITE_OPEN_URLS: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "google mail": "https://mail.google.com",
    "googlemail": "https://mail.google.com",
    "outlook": "https://outlook.live.com",
    "outlook web": "https://outlook.live.com",
    "hotmail": "https://outlook.live.com",
    "github": "https://github.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
}

_CONVERSATIONAL_PREFIX = re.compile(
    r"^(?:o\s+zaman|o\s+halde|şimdi|simdi|sonra|then|now|also|"
    r"bir\s+de|orada|oradan|bana|lütfen|please)\s+",
    re.I,
)
_YOUTUBE_TOKEN = re.compile(
    r"(?:you\s*tube|\byt\b|youtube)",
    re.I,
)
_SITE_FROM_VIDEO = re.compile(
    r"([a-z0-9çğıöşü]+(?:\s+[a-z0-9çğıöşü]+)?)"
    r"['']?(?:dan|den|tan|ten)\s+video\b",
    re.I,
)
# Verb forms only — never match adjective «açık» (aç + ık).
# Include bare «açar» because polite «mısın» may be stripped first.
_OPEN_VERB_CORE = (
    r"açar\s+m[ıi]s[ıi]n|açar\s+musun|açsana|açsene|"
    r"aç(?:ar)?|ac(?:ar)?|"
    r"open(?:ing)?|launch(?:ing)?|başlat|baslat|göster|goster|show"
)
_OPEN_INTENT = re.compile(
    rf"(?<!\w)(?:{_OPEN_VERB_CORE})(?!\w)",
    re.I,
)
_OPEN_VERB_FIND = re.compile(
    rf"(?<!\w)({_OPEN_VERB_CORE})(?!\w)",
    re.I,
)

_POLITE_TOKENS = (
    "lütfen",
    "please",
    "misin",
    "mısın",
    "musun",
    "mu",
    "mı",
    "mi",
    "de",
    "da",
    "efendim",
    "sir",
)

_TR_POLITE_EDGE = re.compile(
    r"^(?:lütfen|please)\s+|\s+(?:lütfen|please)$",
    re.I,
)
_TR_POLITE_SUFFIX = re.compile(
    r"(?:\s+(?:lütfen|please|misin|mısın|musun|mu|mı|mi|de|da|efendim|sir))+$",
    re.I,
)
_TR_OPEN_VERB = re.compile(
    rf"^(?:{_OPEN_VERB_CORE})\s+",
    re.I,
)
_TR_OPEN_VERB_SUFFIX = re.compile(
    r"\s+(?:'u|'yu|u|yu|yi|yı|yı|i|ı|a|e)?\s*"
    rf"(?:{_OPEN_VERB_CORE})\s*$",
    re.I,
)
_TR_CLOSE_VERB_SUFFIX = re.compile(
    r"\s+(?:'u|'yu|u|yu|yi|yı|i|ı)?\s*"
    r"(?:kapat|kapa|close|quit)\s*$",
    re.I,
)

_OPEN_VERBS = (
    "açar mısın",
    "açar misin",
    "açar musun",
    "açsana",
    "açsene",
    "açar",
    "acar",
    "aç",
    "ac",
    "open",
    "launch",
    "başlat",
    "baslat",
    "göster",
    "goster",
    "show",
)


def has_open_verb(text: str) -> bool:
    """True only for open *verbs* — «açık» (adjective) does not count."""
    return bool(_OPEN_VERB_FIND.search((text or "").lower()))


def _strip_polite(text: str) -> str:
    target = (text or "").strip(" .!?,\"'")
    if not target:
        return ""
    prev = None
    while prev != target:
        prev = target
        target = _TR_POLITE_EDGE.sub("", target).strip(" .!?,\"'")
        target = _TR_POLITE_SUFFIX.sub("", target).strip(" .!?,\"'")
    return target


def _strip_conversational(text: str) -> str:
    """Remove follow-up fillers: 'o zaman', 'bana', 'orada', …"""
    target = (text or "").strip(" .!?,\"'")
    if not target:
        return ""
    prev = None
    while prev != target:
        prev = target
        target = _CONVERSATIONAL_PREFIX.sub("", target).strip(" .!?,\"'")
        target = _strip_polite(target)
    return target


def extract_site_url(text: str) -> Optional[str]:
    """Return URL for site-open phrases (YouTube, Gmail, Outlook, …).

    Returns None when the utterance is not a known site-open command.
    """
    raw = _strip_conversational(_strip_polite(text or ""))
    if not raw:
        return None
    lower = raw.lower().strip()

    has_open = bool(_OPEN_INTENT.search(lower))
    youtube_hit = bool(_YOUTUBE_TOKEN.search(lower))

    # Gmail / Google mail account
    if any(
        h in lower
        for h in (
            "gmail",
            "google mail",
            "googlemail",
            "google'dan mail",
            "googledan mail",
            "google dan mail",
            "mail hesab",
        )
    ):
        return SITE_OPEN_URLS["gmail"]

    # Outlook / Hotmail web
    if any(h in lower for h in ("outlook", "hotmail")) and (
        has_open or "mail" in lower or "yaz" in lower
    ):
        return SITE_OPEN_URLS["outlook"]

    # GitHub account/profile — always a website, never a macOS app.
    github_key = normalize_open_target(raw).lower()
    if (
        github_key == "github"
        or any(term in lower for term in ("github", "git hub", "githuub", "githab"))
    ) and (
        has_open
        or any(term in lower for term in ("hesap", "account", "profile", "profil"))
    ):
        return SITE_OPEN_URLS["github"]

    # "youtube" / "youtube aç" / "youtube'dan video aç" / bare yt
    if youtube_hit:
        # Bare site name or open intent — do not treat research chatter as open
        words = lower.split()
        if has_open or len(words) <= 3 or re.search(
            r"(?:you\s*tube|\byt\b|youtube)['']?(?:dan|den)?(?:\s+video)?\s*$",
            lower,
        ):
            return SITE_OPEN_URLS["youtube"]

    # "netflix'den video aç" style → known SITE_OPEN_URLS only
    if has_open:
        m = _SITE_FROM_VIDEO.search(lower)
        if m:
            site = normalize_open_target(m.group(1))
            url = SITE_OPEN_URLS.get(site.lower())
            if url:
                return url
    return None


def normalize_open_target(raw: str) -> str:
    """Strip polite Turkish suffixes and speech artifacts from an app target."""
    target = _strip_conversational(_strip_polite(raw))
    if not target:
        return ""

    target = re.sub(r"^(?:the|uygulama|app|bana)\s+", "", target, flags=re.I)
    target = _TR_OPEN_VERB.sub("", target)
    target = _TR_OPEN_VERB_SUFFIX.sub("", target)
    target = _TR_CLOSE_VERB_SUFFIX.sub("", target)
    target = _strip_polite(target)
    # "youtube'dan video" / ablative + media filler
    target = re.sub(
        r"['']?(?:dan|den|tan|ten)\s+video\b",
        "",
        target,
        flags=re.I,
    ).strip()
    target = re.sub(r"['']?(?:dan|den|tan|ten)\s*$", "", target, flags=re.I).strip()
    target = re.sub(r"\s+video\s*$", "", target, flags=re.I).strip()
    target = _strip_conversational(target)

    lower = target.lower()
    if lower in SPEECH_APP_ALIASES:
        return SPEECH_APP_ALIASES[lower]

    # "Chrome'u" → "Chrome"
    target = re.sub(r"['']u$|['']yu$|u$|yu$|yi$|yı$", "", target, flags=re.I)
    target = target.strip()
    lower = target.lower()
    if lower in SPEECH_APP_ALIASES:
        return SPEECH_APP_ALIASES[lower]
    if _YOUTUBE_TOKEN.search(lower):
        return "youtube"
    return target


_MERGED_OPEN_TAIL = re.compile(
    r"^(?P<stem>.+?)(?:'?(?:u|yu|yi|yı|i|ı)?)?(?:aç|ac|açar|acar|açsana|acsana)$",
    re.I,
)


def extract_merged_open_target(text: str) -> str | None:
    """STT often merges «code aç» → «codeac» on the final word."""
    raw = _strip_conversational(_strip_polite(text or ""))
    if not raw:
        return None
    words = raw.split()
    if not words:
        return None
    last = words[-1]
    m = _MERGED_OPEN_TAIL.match(last)
    if not m:
        return None
    stem = (m.group("stem") or "").strip()
    if len(stem) < 2:
        return None
    prefix = " ".join(words[:-1]).strip()
    combined = f"{prefix} {stem}".strip() if prefix else stem
    candidate = normalize_open_target(combined)
    return candidate or None


def extract_open_target(text: str) -> str | None:
    """Extract app name from mixed TR/EN open phrases."""
    raw = _strip_conversational(_strip_polite(text or ""))
    if not raw:
        return None
    lower = raw.lower()

    # Adjective «açık» is never an open verb — reject early.
    if not has_open_verb(lower):
        return None

    # "<app> açar mısın" / "chrome'u aç" / "chrome aç" / "chrome açsana"
    m = re.search(
        r"^(.+?)\s+(?:'u|'yu|u|yu|yi|yı|i|ı)?\s*"
        rf"(?:{_OPEN_VERB_CORE})\s*$",
        lower,
        re.I,
    )
    if m:
        start, end = m.span(1)
        candidate = normalize_open_target(raw[start:end])
        if candidate:
            return candidate

    # Prefix verb: "aç chrome" / "open chrome" / "açsana spotify"
    m_pref = re.match(rf"^(?:{_OPEN_VERB_CORE})\s+(.+)$", lower, re.I)
    if m_pref:
        start, end = m_pref.span(1)
        candidate = normalize_open_target(raw[start:end])
        if candidate:
            return candidate

    # Word-boundary verb scan (never substring of «açık»)
    for m in _OPEN_VERB_FIND.finditer(lower):
        after = normalize_open_target(raw[m.end() :])
        before = normalize_open_target(raw[: m.start()])
        if before and after.lower() in _POLITE_TOKENS:
            return before
        if before and (not after or after.lower() in _POLITE_TOKENS):
            return before
        if after and after.lower() not in _POLITE_TOKENS:
            return after
        if before:
            return before
    return None


def extract_close_target(text: str) -> str | None:
    """Extract app name from close/quit phrases (e.g. spotify kapat)."""
    raw = _strip_polite(text or "")
    if not raw:
        return None
    lower = raw.lower()

    m = re.search(
        r"^(.+?)\s+(?:'u|'yu|u|yu|yi|yı|i|ı)?\s*"
        r"(?:kapat|kapa|close|quit)\s*$",
        lower,
        re.I,
    )
    if m:
        start, end = m.span(1)
        candidate = normalize_open_target(raw[start:end])
        if candidate:
            return candidate

    for prefix in ("kapat ", "kapa ", "close ", "quit "):
        if lower.startswith(prefix):
            candidate = normalize_open_target(raw[len(prefix) :])
            if candidate:
                return candidate

    for word in ("kapat", "kapa", "close", "quit"):
        if word not in lower:
            continue
        idx = lower.index(word)
        before = normalize_open_target(raw[:idx])
        after = normalize_open_target(raw[idx + len(word) :])
        if before:
            return before
        if after:
            return after
    return None


@dataclass(frozen=True)
class MusicIntent:
    """Parsed play/listen intent — never blank YouTube homepage."""

    query: str
    service: str = "youtube"  # youtube | spotify


_MUSIC_WORD = (
    r"(?:müziğ[iıüû]|muzig[ii]|müzik|muzik|şarkıs[ıi]|sarkis[ii]|şarkı|sarki|"
    r"track|song|music)"
)
_PLAY_VERB = r"(?:aç|ac|çal|cal|oynat|play|başlat|baslat)"
_SPOTIFY_TOKEN = re.compile(r"spotify", re.I)

# "Koray Avcı müziği aç" / "X şarkısı çal"
_MUSIC_NOUN_PLAY = re.compile(
    rf"^(.+?)\s+{_MUSIC_WORD}\s*{_PLAY_VERB}?\s*$",
    re.I,
)
# "play Koray Avcı" / "çal Koray Avcı"
_PLAY_PREFIX = re.compile(
    rf"^(?:play|çal|cal|dinle)\s+(.+?)\s*$",
    re.I,
)
# "Koray Avcı dinle"
_LISTEN_SUFFIX = re.compile(
    r"^(.+?)\s+dinle(?:\s+m[ıi]s[ıi]n)?\s*$",
    re.I,
)
# "spotify'da X aç" / "youtube'da X ara"
_SERVICE_SEARCH = re.compile(
    rf"^(?:spotify|you\s*tube|youtube|yt)['']?(?:da|de|dan|den)?\s+"
    rf"(.+?)(?:\s+(?:{_PLAY_VERB}|ara|search))?\s*$",
    re.I,
)


def youtube_search_url(query: str) -> str:
    q = quote_plus((query or "").strip())
    return f"https://www.youtube.com/results?search_query={q}"


def spotify_search_url(query: str) -> str:
    q = quote_plus((query or "").strip())
    return f"https://open.spotify.com/search/{q}"


def extract_music_intent(text: str) -> Optional[MusicIntent]:
    """Detect play/listen music intents with a searchable query.

    Returns None for bare site opens («youtube aç») — those stay site-open.
    Vague «şarkı aç» / «güzel bir şarkı» still returns an intent; decision layer
    chooses a concrete track at play time.
    """
    raw = _strip_conversational(_strip_polite(text or ""))
    if not raw:
        return None
    lower = raw.lower().strip()

    # Close/quit is never a play intent («spotify kapat»)
    if re.search(r"(?<!\w)(?:kapat|kapa|close|quit)(?!\w)", lower):
        return None

    # Bare YouTube / Spotify open — not a search
    if re.fullmatch(
        r"(?:you\s*tube|youtube|yt|spotify)(?:\s+(?:aç|ac|open|başlat|baslat))?",
        lower,
    ):
        return None
    if re.fullmatch(
        r"(?:you\s*tube|youtube)['']?(?:dan|den)?\s+video(?:\s+(?:aç|ac|open))?",
        lower,
    ):
        return None

    service = "spotify" if _SPOTIFY_TOKEN.search(lower) else "youtube"

    # Bare / vague play: "şarkı aç", "müzik aç", "bir şarkı aç", "play music"
    if re.fullmatch(
        rf"(?:(?:bana|bir)\s+)?{_MUSIC_WORD}\s*{_PLAY_VERB}\s*",
        lower,
    ) or re.fullmatch(
        rf"(?:play|çal|cal)\s+(?:(?:some|a)\s+)?{_MUSIC_WORD}\s*",
        lower,
    ):
        return MusicIntent(query="şarkı", service=service)

    def _query_from_match(m: re.Match[str]) -> str:
        start, end = m.span(1)
        return _clean_music_query(raw[start:end])

    m = _SERVICE_SEARCH.match(lower)
    if m:
        query = _query_from_match(m)
        if query and len(query) >= 2:
            return MusicIntent(query=query, service=service)

    m = _MUSIC_NOUN_PLAY.match(lower)
    if m:
        query = _query_from_match(m)
        if query and len(query) >= 2:
            if re.search(_PLAY_VERB, lower) or re.search(_MUSIC_WORD, lower):
                return MusicIntent(query=query, service=service)
        # "güzel bir şarkı aç" cleaned to too-short / filler → still intent
        if re.search(_PLAY_VERB, lower) and re.search(_MUSIC_WORD, lower):
            frag = (m.group(1) or "").strip() or "şarkı"
            return MusicIntent(query=frag if frag else "şarkı", service=service)

    m = _PLAY_PREFIX.match(lower)
    if m:
        query = _query_from_match(m)
        query = re.sub(rf"\s+{_MUSIC_WORD}\s*$", "", query, flags=re.I).strip()
        if query and len(query) >= 2:
            return MusicIntent(query=query, service=service)

    m = _LISTEN_SUFFIX.match(lower)
    if m:
        query = _query_from_match(m)
        query = re.sub(rf"\s+{_MUSIC_WORD}\s*$", "", query, flags=re.I).strip()
        if query and len(query) >= 2:
            return MusicIntent(query=query, service=service)

    return None


def _clean_music_query(fragment: str) -> str:
    q = (fragment or "").strip(" .!?,\"'")
    q = re.sub(
        r"^(?:bana|lütfen|please|the|bir)\s+",
        "",
        q,
        flags=re.I,
    ).strip()
    q = re.sub(
        rf"\s+{_MUSIC_WORD}\s*$",
        "",
        q,
        flags=re.I,
    ).strip()
    q = re.sub(
        r"^(?:spotify|you\s*tube|youtube|yt)['']?(?:da|de|dan|den)?\s+",
        "",
        q,
        flags=re.I,
    ).strip()
    return q.strip(" .!?,\"'")
