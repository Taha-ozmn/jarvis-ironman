"""Speech text cleanup — strip formal address, robotic filler, TTS phrasing."""

from __future__ import annotations

import html
import re

# ", efendim." / " efendim," / leading "Efendim,"
_EFENDIM_TRAIL = re.compile(
    r"(?:,\s*)?\befendim\b\.?",
    re.IGNORECASE,
)
_EFENDIM_LEAD = re.compile(
    r"^\s*\befendim\b\s*[,:]?\s*",
    re.IGNORECASE,
)
_MULTI_SPACE = re.compile(r"\s{2,}")
_EDGE_PUNCT = re.compile(r"^[\s,;:]+|[\s,;:]+$")

_EN_COULD_NOT_OPEN = re.compile(
    r"(?i)^could\s+not\s+open\s+(.+)$",
)
_EN_GENERIC_FAIL = re.compile(
    r"(?i)^(tool\s+action\s+failed|open\s+failed|open\s+timed\s+out|"
    r"failed\s+to\s+\w+|error[:\s].*|permission\s+denied.*)\.?$",
)

# Chatbot / telegraphic TTS filler — leading or whole-utterance.
_LEADING_ROBOTIC = re.compile(
    r"^\s*(?:"
    r"bakıyorum|bakiyorum|hemen bakıyorum|hemen bakiyorum|"
    r"kontrol ediyorum|şu anda bakıyorum|su anda bakiyorum|"
    r"let me (?:check|look|see)|i(?:'m| am) (?:checking|looking)"
    r")\s*[.!]?\s+",
    re.IGNORECASE,
)
_WHOLE_ROBOTIC = re.compile(
    r"^\s*(?:"
    r"bakıyorum|bakiyorum|hemen bakıyorum|hemen bakiyorum|"
    r"kontrol ediyorum"
    r")\s*[.!]?\s*$",
    re.IGNORECASE,
)
_CHATBOT_FILLER = re.compile(
    r"(?i)\b(?:as an ai(?: assistant)?|as a language model|"
    r"how can i (?:help|assist) you today|"
    r"tabii ki memnuniyetle (?:size )?yardımcı olurum|"
    r"size nasıl yardımcı olabilirim(?: bugün)?)\b[^.!?]*[.!?]?\s*",
)

# SSML break after punctuation (inner fragment; Communicate wraps <prosody>).
_BREAK_COMMA_MS = 160
_BREAK_CLAUSE_MS = 220
_BREAK_SENTENCE_MS = 320
_MAX_PHRASE_CHARS = 160
_MAX_PHRASE_CHUNKS = 4
_MIN_PHRASE_CHARS = 12


def strip_efendim(text: str) -> str:
    """Remove all 'efendim' / 'Efendim' from spoken or Cursor output."""
    if not text:
        return text
    had_terminal = bool(re.search(r"[.!?]\s*$", text))
    cleaned = _EFENDIM_LEAD.sub("", text)
    cleaned = _EFENDIM_TRAIL.sub("", cleaned)
    cleaned = _MULTI_SPACE.sub(" ", cleaned).strip()
    cleaned = re.sub(r"\s+([.!?])", r"\1", cleaned)
    cleaned = re.sub(r",\s*\.", ".", cleaned)
    cleaned = _EDGE_PUNCT.sub("", cleaned).strip()
    if had_terminal and cleaned and not re.search(r"[.!?]$", cleaned):
        cleaned += "."
    return cleaned


def strip_robotic_filler(text: str) -> str:
    """Drop telegraphic 'Bakıyorum.' spam and chatbot filler — keep real content."""
    t = (text or "").strip()
    if not t:
        return t
    if _WHOLE_ROBOTIC.match(t):
        return ""
    prev = None
    while prev != t:
        prev = t
        t = _LEADING_ROBOTIC.sub("", t).strip()
    t = _CHATBOT_FILLER.sub("", t)
    t = _MULTI_SPACE.sub(" ", t).strip()
    t = _EDGE_PUNCT.sub("", t).strip()
    return t


def speak_safe_tr(text: str) -> str:
    """Ensure spoken tool errors are Turkish — never raw English failures."""
    t = strip_robotic_filler(strip_efendim((text or "").strip()))
    if not t:
        return t
    m = _EN_COULD_NOT_OPEN.match(t)
    if m:
        target = m.group(1).strip().strip("\"'«»")
        if target:
            return f"«{target}» açılamadı."
        return "Açılamadı."
    if re.search(r"(?i)permission\s+denied", t):
        return "İzin reddedildi (Permission denied)."
    if _EN_GENERIC_FAIL.match(t):
        return "İşlem başarısız oldu."
    if re.match(r"(?i)^(could not|failed to|unable to)\b", t):
        return "İşlem başarısız oldu."
    return t



def speak_safe(text: str, language: str = "en-GB") -> str:
    """Clean TTS text. Spoken path stays English — do not auto-switch to TR."""
    lang = (language or "en-GB").lower()
    # Never translate spoken replies to Turkish from language auto-detect.
    if lang.startswith("tr"):
        return strip_robotic_filler(strip_efendim((text or "").strip()))
    return strip_robotic_filler(strip_efendim((text or "").strip()))


def normalize_for_dedupe(text: str) -> str:
    """Normalize phrase for duplicate-speech detection."""
    t = strip_robotic_filler(strip_efendim(text or ""))
    t = t.lower().strip(" .,!?;:\"'")
    t = _MULTI_SPACE.sub(" ", t)
    return t


def split_speech_phrases(
    text: str,
    *,
    max_chunk: int = _MAX_PHRASE_CHARS,
    max_chunks: int = _MAX_PHRASE_CHUNKS,
) -> list[str]:
    """Split long replies into natural phrases without tiny fragments.

    Keeps latency bounded: at most ``max_chunks`` pieces; short tails merge.
    """
    raw = _MULTI_SPACE.sub(" ", (text or "").strip())
    if not raw:
        return []
    if len(raw) <= max_chunk:
        sentences = [p.strip() for p in re.split(r"(?<=[.!?])\s+", raw) if p.strip()]
        if len(sentences) <= 1:
            return [raw]
        if len(sentences) <= max_chunks:
            return _merge_short_phrases(sentences)
        return _pack_phrases(sentences, max_chunk, max_chunks)

    sentences = [p.strip() for p in re.split(r"(?<=[.!?])\s+", raw) if p.strip()]
    if not sentences:
        sentences = [raw]
    expanded: list[str] = []
    for sent in sentences:
        if len(sent) <= max_chunk:
            expanded.append(sent)
            continue
        parts = [p.strip() for p in re.split(r"(?<=[,;:])\s+", sent) if p.strip()]
        if len(parts) == 1:
            expanded.append(sent)
        else:
            expanded.extend(parts)
    return _pack_phrases(expanded, max_chunk, max_chunks)


def _merge_short_phrases(parts: list[str]) -> list[str]:
    out: list[str] = []
    for part in parts:
        if out and len(part) < _MIN_PHRASE_CHARS:
            out[-1] = f"{out[-1]} {part}".strip()
        else:
            out.append(part)
    return out or parts


def _pack_phrases(parts: list[str], max_chunk: int, max_chunks: int) -> list[str]:
    packed: list[str] = []
    buf = ""
    for part in parts:
        candidate = f"{buf} {part}".strip() if buf else part
        if buf and len(candidate) > max_chunk:
            packed.append(buf)
            buf = part
        else:
            buf = candidate
    if buf:
        packed.append(buf)
    packed = _merge_short_phrases(packed)
    if len(packed) <= max_chunks:
        return packed
    # Merge overflow into the last allowed chunk (avoid N sequential TTS round-trips).
    head = packed[: max_chunks - 1]
    tail = " ".join(packed[max_chunks - 1 :])
    return head + [tail]


def tts_inner_ssml(
    text: str,
    *,
    comma_ms: int = _BREAK_COMMA_MS,
    clause_ms: int = _BREAK_CLAUSE_MS,
    sentence_ms: int = _BREAK_SENTENCE_MS,
) -> str:
    """XML-escaped prose plus <break> after punctuation for edge-tts Communicate.text.

    Communicate wraps this in <speak><voice><prosody>…</prosody>. Do not nest <speak>.
    """
    escaped = html.escape((text or "").strip(), quote=False)
    if not escaped:
        return ""

    def _break(ms: int) -> str:
        return f'<break time="{int(ms)}ms"/>'

    # Sentence-ending punctuation first (do not treat '.' inside numbers as a stop).
    escaped = re.sub(
        r"(?<!\d)([.!?])(?=\s|$)",
        lambda m: f"{m.group(1)}{_break(sentence_ms)}",
        escaped,
    )
    escaped = re.sub(
        r"([;:])(?=\s)",
        lambda m: f"{m.group(1)}{_break(clause_ms)}",
        escaped,
    )
    escaped = re.sub(
        r"(,)(?=\s)",
        lambda m: f"{m.group(1)}{_break(comma_ms)}",
        escaped,
    )
    return escaped
