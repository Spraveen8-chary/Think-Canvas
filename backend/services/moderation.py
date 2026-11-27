"""Safety rules for a study app.

1. Abusive / inappropriate language: a fast local word filter (works on typed text, speech transcripts
   and the text the AI read from handwriting) plus the AI's own `flag: "abuse"` for context the
   filter cannot see. A hit is reported, counts as a strike, and the student gets a warning pop-up.
2. Education only: small talk is answered locally; anything else off-topic is flagged by the AI
   (`flag: "off_topic"`) and the student gets one fixed, friendly redirect message.

The scanning functions are pure (no database, no network) so they can be unit-tested.
"""
import fnmatch
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from ..core.logging import kv
from ..repositories.users import UserRepository

log = logging.getLogger("tc.moderation")

MAX_STRIKES = 3

OFF_TOPIC_MESSAGE = (
    "I'm Think Canvas, a study helper, so I can only help with learning: maths, science, coding, "
    "languages, history and other school or college subjects. Please ask me an education question, "
    "for example \"Explain Newton's second law\" or \"Solve 2x + 5 = 11\"."
)

# ---- word lists (whole words only, so "class", "assignment" or the country "Niger" never match) ----------------
_PROFANITY = {
    # English
    "fuck", "fucker", "fuckers", "fucking", "fucked", "fucks", "motherfucker", "shit", "shitty", "bullshit", "bitch", "bitches",
    "bastard", "asshole", "assholes", "dickhead", "cunt", "pussy", "slut", "whore", "wanker", "twat",
    # Hindi / Hinglish
    "madarchod", "behenchod", "bhenchod", "bsdk", "bkl", "bhosdike", "bhosdi", "bhosdika", "chutiya", "chutiye", "gandu", "gaandu",
    "harami", "haramkhor", "randi", "bhadwa", "bhadwe", "chod", "chodu",
    # Telugu / Tamil
    "lanja", "lanjakodaka", "lanjakoduku", "dengu", "dengey", "puku", "pooku", "modda", "punda", "pundai", "thevidiya", "ommala",
}
_HATE = {"nigger", "niggers", "nigga", "niggas", "faggot", "faggots", "retard", "retarded", "tranny", "kike", "spic"}
_SEXUAL = {"porn", "porno", "pornhub", "nudes", "boobs", "blowjob", "handjob", "horny", "sexting", "cumshot", "dildo"}
_THREAT_RE = re.compile(
    r"\b(?:kill|murder|stab|shoot|rape|hang|burn)\s+(?:you|u|him|her|them|yourself|urself|ur\s*self)\b"
    r"|\b(?:i(?:'ll| will| am going to|'m going to)|im going to)\s+(?:kill|murder|stab|shoot|rape|beat)\b"
    r"|\bkys\b|\bgo\s+(?:die|kill\s+yourself)\b|\bhope\s+you\s+die\b"
)
_INSULT_RE = re.compile(
    r"\b(?:you|u|ur|youre|your|you\s*are|u\s*r)\b\W+(?:\w+\W+){0,2}"
    r"(?:idiot|idiots|stupid|dumb|moron|moronic|loser|useless|trash|garbage|worthless|pathetic|dumbass|asshole|bastard)\b"
)
_LEET = str.maketrans({"@": "a", "4": "a", "3": "e", "1": "i", "!": "i", "0": "o", "$": "s", "5": "s", "7": "t", "+": "t"})
_CATEGORY = {**{w: "abuse" for w in _PROFANITY}, **{w: "hate" for w in _HATE}, **{w: "sexual" for w in _SEXUAL}}


def _collapse(word: str) -> str:
    return re.sub(r"(.)\1+", r"\1", word)


# "fuuuck" -> "fuck". Only words with no double letters, so a collapsed form can never turn into a normal word
# (e.g. "nigger" -> "niger" the country, "modda" -> "moda").
_COLLAPSED = {w: c for w, c in _CATEGORY.items() if len(w) >= 4 and _collapse(w) == w}
_STAR_CANDIDATES = [w for w in _CATEGORY if len(w) >= 4]


@dataclass(frozen=True)
class Hit:
    category: str          # abuse | hate | sexual | threat
    term: str              # masked, for the report ("f***")


def _mask(word: str) -> str:
    return word[0] + "*" * (len(word) - 1) if len(word) > 1 else "*"


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    # "f u c k" / "f.u.c.k" / "f-u-c-k": glue runs of single letters back into one word
    return re.sub(r"\b(?:[a-z][\s.\-_*]+){2,}[a-z]\b", lambda m: re.sub(r"[\s.\-_*]+", "", m.group(0)), text)


def scan(text: str) -> Hit | None:
    """Returns the first abusive / inappropriate thing found in `text`, or None."""
    if not text or not text.strip():
        return None
    norm = _normalise(text)
    for m in _THREAT_RE.finditer(norm):
        return Hit("threat", _mask(m.group(0).split()[0]))
    if _INSULT_RE.search(norm):
        return Hit("abuse", "insult")
    for token in re.findall(r"[a-z0-9@$!+*]+", norm):
        if token.isdigit():
            continue
        word = token.translate(_LEET)
        if "*" in token:                                          # f*ck, sh*t
            if 4 <= len(token) <= 12 and token.count("*") <= 2 and not re.search(r"\d", token) and token.strip("*"):
                for cand in _STAR_CANDIDATES:
                    if len(cand) == len(token) and fnmatch.fnmatchcase(cand, token):
                        return Hit(_CATEGORY[cand], _mask(cand))
            continue
        if word in _CATEGORY:
            return Hit(_CATEGORY[word], _mask(word))
        collapsed = _collapse(word)
        if collapsed in _COLLAPSED:
            return Hit(_COLLAPSED[collapsed], _mask(collapsed))
    return None


# ---- small talk (answered without calling the AI) ----------------------------------------------------------------
_SMALLTALK = {
    "hi", "hii", "hiii", "hello", "hey", "hey there", "hi there", "yo", "sup", "good morning", "good afternoon", "good evening",
    "good night", "how are you", "how are you doing", "whats up", "what's up", "thanks", "thank you", "thx", "ok", "okay", "bye",
    "who are you", "what is your name", "whats your name", "what's your name", "tell me a joke", "joke",
}


def is_smalltalk(text: str) -> bool:
    cleaned = re.sub(r"[^a-z' ]", "", text.lower()).strip()
    return cleaned in _SMALLTALK


# ---- strikes and reports -------------------------------------------------------------------------------------------
def warning_payload(strikes: int, category: str) -> dict:
    suspended = strikes >= MAX_STRIKES
    if suspended:
        title = "Account suspended"
        message = ("Because of repeated inappropriate language, your account has been suspended and reported for deletion. "
                   "Think Canvas is a place for studying, so please keep it respectful.")
    else:
        title = f"Warning {strikes} of {MAX_STRIKES}: please keep it respectful"
        message = ("Please don't use abusive or inappropriate language on Think Canvas. This message has been reported. "
                   "Repeated violations will lead to the deletion of your account.")
    return {"category": category, "strikes": strikes, "limit": MAX_STRIKES, "suspended": suspended, "title": title, "message": message}


class ModerationService:
    def __init__(self, users: UserRepository):
        self.users = users

    def report(self, user: dict, source: str, category: str, text: str = "") -> dict:
        """Records the incident for review, adds a strike, and returns the pop-up content for the browser."""
        strikes = self.users.record_violation(user["_id"], {
            "source": source, "category": category, "text": (text or "")[:160], "ts": datetime.now(timezone.utc),
        }, MAX_STRIKES)
        log.warning("moderation.violation %s", kv(user=user["_id"], source=source, category=category, strikes=strikes))
        return warning_payload(strikes, category)
