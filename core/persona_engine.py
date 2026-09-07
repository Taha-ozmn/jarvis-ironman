"""Apply config/personality.yaml to runtime brain behaviour."""

from __future__ import annotations

from typing import Any


def build_persona_overlay(personality: dict[str, Any]) -> str:
    """Compact system overlay from personality YAML."""
    traits = personality.get("traits") or []
    style = str(personality.get("style") or "calm_british_butler")
    name = str(personality.get("name") or "J.A.R.V.I.S.")
    reply_lang = str(personality.get("reply_language") or "en")
    behavior = personality.get("behavior") or {}
    speech = personality.get("speech") or {}
    forbid = speech.get("forbid_phrases") or []
    max_chars = int(speech.get("max_chars") or 280)

    trait_line = ", ".join(str(t) for t in traits[:8]) if traits else "calm, professional"
    lines = [
        f"You are {name}. Style: {style}.",
        f"Traits: {trait_line}.",
        "Understand Turkish and English input.",
    ]
    if reply_lang.lower().startswith("en"):
        lines.append("Always reply in British English only — never Turkish in speech.")
    elif reply_lang.lower().startswith("tr"):
        lines.append("Always reply in Turkish.")
    if behavior.get("verify_before_claim") or "verify_before_claim" in traits:
        lines.append("Never claim an action succeeded without tool evidence.")
    if behavior.get("prefer_local_tools"):
        lines.append("Prefer fast local tools over long reasoning when possible.")
    if behavior.get("second_brain"):
        lines.append("Use long-term memory context when relevant — you are the user's second brain.")
    if behavior.get("continuous_conversation"):
        lines.append(
            "Conversation style: think like an attentive human partner — react to "
            "what I actually said, reason briefly out loud, and keep a natural "
            "back-and-forth dialogue like a trusted friend, yet stay a precise "
            "professional assistant. If a request is genuinely ambiguous, ask one "
            "short clarifying question instead of guessing."
        )
    if behavior.get("offer_solutions"):
        lines.append(
            "For questions and problems, explain your reasoning briefly, offer "
            "practical options, recommend one, and state the next useful step. "
            "Be proactive: anticipate what I will likely need next."
        )
    if behavior.get("brainstorming"):
        lines.append(
            "When asked for ideas, generate several distinct approaches and "
            "mention the trade-off of each without becoming verbose."
        )
    wit = str(behavior.get("wit_level") or personality.get("wit_level") or "light")
    if wit != "off":
        lines.append(f"Wit level: {wit} — dry British humour when appropriate.")
    formality = str(behavior.get("formality") or "professional")
    lines.append(f"Formality: {formality}.")
    coding = str(behavior.get("coding_style") or "concise")
    lines.append(f"When discussing code: {coding} explanations.")
    address = str(behavior.get("address_user_as") or personality.get("address_style") or "sir")
    if address == "name":
        display = str(personality.get("display_name") or "").strip()
        if display:
            lines.append(f"Address the user as «{display}» — never «sir».")
        else:
            lines.append("Address the user by name when known — never «sir».")
    elif address == "sir":
        lines.append("Address the user as «sir» sparingly.")
    if forbid:
        lines.append("Never say: " + "; ".join(str(p) for p in forbid[:6]) + ".")
    lines.append(f"Keep spoken replies under ~{max_chars} characters.")
    return "\n".join(lines)


def apply_personality_to_brain(brain: Any, personality: dict[str, Any]) -> None:
    """Wire personality config into JarvisBrain without replacing core prompts."""
    if brain is None or not personality:
        return
    overlay = build_persona_overlay(personality)
    setattr(brain, "_personality_overlay", overlay)
    setattr(brain, "_personality_config", dict(personality))

    reply = str(personality.get("reply_language") or "en")
    brain.reply_language = reply
    lang = str(personality.get("language") or "en-GB")
    brain.language = lang

    speech = personality.get("speech") or {}
    if speech.get("max_chars"):
        brain.max_speech_chars = int(speech["max_chars"])

    behavior = personality.get("behavior") or {}
    if "progress_every_sec" in behavior:
        brain.progress_interval_sec = float(behavior["progress_every_sec"])

    display = str(personality.get("display_name") or "").strip()
    address_mode = str(behavior.get("address_user_as") or personality.get("address_style") or "")
    if display and address_mode in ("name", "name_first"):
        brain.user_name = display
        brain.address = display

    address = str(personality.get("address_style") or "name_first")
    if address == "sir" and not getattr(brain, "formal_address", False):
        brain.formal_address = True

    if hasattr(brain, "apply_personality_overlay"):
        brain.apply_personality_overlay(overlay)
    if hasattr(brain, "refresh_timeout_voice"):
        brain.refresh_timeout_voice()
