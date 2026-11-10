"""Step 2 - A simple, free emotion check that does not use AI.

Research basis (see README):
  * Berger & Milkman (2012): "heart-racing" (high-arousal) emotions such as
    anger, anxiety/fear and awe spread more; calm (low-arousal) emotions such
    as sadness spread less.
  * Loewenstein (1994): curiosity = an "information gap"; a question the viewer
    can't answer yet.

We use two signals that come straight from the script:
  1. The emotion tags the writer put on each line, e.g. (Gloating, Smug).
  2. Strong words in the line itself, e.g. "poison", "hang", "betray", "slap".

This gives a score from 0 (calm) to 1 (heart-racing). The AI's opinion is
compared with this score later. If they disagree, the promo gets flagged.
"""
from __future__ import annotations

import re

from .parse import Line

# Viewer emotions we ask the AI to choose from. HIGH = good for hooks.
HIGH_AROUSAL_EMOTIONS = {"anger", "shock", "fear", "triumph", "desire"}
LOW_AROUSAL_EMOTIONS = {"sadness", "tenderness", "calm"}
ALL_EMOTIONS = sorted(HIGH_AROUSAL_EMOTIONS | LOW_AROUSAL_EMOTIONS | {"curiosity", "humor"})

# Script tags (lower-case word stems) -> heated or calm.
HIGH_TAGS = [
    "outrag", "furious", "fury", "angr", "enrag", "rage", "venom", "fierce", "vicious",
    "cruel", "gloat", "mock", "smug", "sinister", "menac", "threat", "chill", "ruthless",
    "shock", "stun", "gasp", "horrif", "terrif", "fear", "panic", "desperat", "scream",
    "crying out", "shout", "yell", "accus", "defian", "triumph", "exult", "command",
    "savage", "hysteric", "frantic", "piercing", "scorn", "disgust", "betray", "explosi",
    "roar", "seeth", "snarl", "vengeful", "ominous", "predator", "callous", "contempt",
    "incredulous", "alarm", "urgent", "aggress", "hostile", "taunt", "sneer", "deadly",
]
LOW_TAGS = [
    "soft", "gentle", "tender", "weary", "quiet", "calm", "sad", "melanchol", "wistful",
    "tired", "hesitant", "warm", "loving", "kind", "sleepy", "pensive", "reflective",
    "nostalg", "content", "peaceful", "polite", "casual", "neutral", "resigned",
]

# Strong words in dialogue / action (word stems).
HIGH_WORDS = [
    "betray", "liar", "lie", "kill", "murder", "poison", "hang", "noose", "gallows", "witch",
    "slap", "blood", "dead", "die", "death", "marry", "marrying", "pregnan", "baby", "divorce",
    "affair", "secret", "never", "burn", "destroy", "reveng", "prison", "arrest", "steal",
    "cheat", "disgrace", "monster", "hate", "curse", "condemn", "mistress", "heir", "disown",
    "banish", "knife", "dagger", "gun", "trap", "frame", "guilty", "traitor", "whore", "bastard",
    "strike", "struck", "grab", "shove", "throw", "collapse", "faint", "kiss", "stab", "pin",
    "chok", "seiz", "drag", "rip", "smash", "shatter", "chain", "slam", "punch", "scream",
    "humiliat", "fake", "impostor", "truth", "who are you", "you knew", "how dare",
    "real father", "real mother", "not my", "get out", "on your knees", "kneel", "snatch", 
    "fling", "flung", "hurl", "toss", "yank", "spit", "throttle", "dead to",
]
_WORD_RE = {w: re.compile(r"\b" + re.escape(w), re.I) for w in HIGH_WORDS}


def tag_score(line: Line) -> float | None:
    """1 = heated tag, 0 = calm tag, None = no useful tag."""
    if not line.tags:
        return None
    joined = " ".join(line.tags).lower()
    hi = any(t in joined for t in HIGH_TAGS)
    lo = any(t in joined for t in LOW_TAGS)
    if hi and not lo:
        return 1.0
    if lo and not hi:
        return 0.0
    if hi and lo:
        return 0.9
    return 0.5


def word_hits(text: str) -> list[str]:
    return [w for w, rx in _WORD_RE.items() if rx.search(text)]


def arousal(line: Line) -> float:
    """0..1 'how heart-racing is this line' from tags + words + punctuation."""
    words = word_hits(line.text)
    w = min(1.0, len(words) / 2)
    t = tag_score(line)
    punch = 0.15 if "!" in line.text else 0.0
    if line.kind == "camera":
        # Camera notes describe the picture; they matter less on their own.
        return round(min(1.0, 0.5 * w), 3)
    if t is None:
        return round(min(1.0, 0.25 + 0.6 * w + punch), 3)
    return round(min(1.0, 0.55 * t + 0.35 * w + punch), 3)


def window_arousal(lines: list[Line], start: float, end: float) -> float:
    """Highest arousal of any dialogue/action line inside a time window."""
    vals = [arousal(l) for l in lines
            if l.kind in ("dialogue", "action") and l.start < end and l.end > start]
    return max(vals, default=0.0)


def agreement(ai_emotion: str, code_arousal: float) -> tuple[float, str | None]:
    """Does the AI's emotion agree with the script's own signals?

    Returns (score 0..1, flag text or None).
    """
    e = (ai_emotion or "").lower().strip()
    if e in HIGH_AROUSAL_EMOTIONS:
        if code_arousal >= 0.6:
            return 1.0, None
        if code_arousal >= 0.4:
            return 0.6, None
        return 0.2, f"AI says '{e}' but script tags/words look calm"
    if e in LOW_AROUSAL_EMOTIONS:
        if code_arousal >= 0.7:
            return 0.5, f"AI says calm '{e}' but script looks heated"
        return 0.4, f"hook emotion is low-energy '{e}' (research: spreads less)"
    return 0.6, None  # curiosity / humor / unknown: neutral
