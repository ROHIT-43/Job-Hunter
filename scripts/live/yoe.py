"""yoe.py — Years-of-experience requirement from a job's title + description.

parse_yoe() returns the JD's *headline* minimum: the highest floor among all
experience mentions ("3+ years overall ... 1+ year of Kafka" -> 3), because the
headline bar is what a candidate must clear. Ranges contribute their lower bound
("1-3 years" -> 1). Returns None when nothing is stated.
"""
import re

_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_NUM = r"(\d{1,2}(?:\.\d)?|" + "|".join(_WORDS) + r")"
_YRS = r"(?:years?|yrs?)"
# Words that may sit between "N years" and "experience": "of relevant industry".
_GAP = r"(?:\s+(?:of|in|as|with|relevant|professional|industry|hands-on|"\
       r"working|work|total|overall|software|development|engineering|"\
       r"backend|frontend|full[- ]stack|programming|coding|technical|"\
       r"proven|prior|related|practical)){0,4}"

_PATTERNS = [
    # "1-3 years", "2 to 4 yrs", "0–2 years of experience"
    re.compile(_NUM + r"\s*(?:-|–|—|to)\s*" + _NUM + r"\s*\+?\s*" + _YRS),
    # "2+ years", "3 + yrs"
    re.compile(_NUM + r"\s*\+\s*" + _YRS),
    # "minimum 2 years", "at least two years", "min. of 3 yrs"
    re.compile(r"(?:minimum|min\.?|at\s*least|atleast)\s*(?:of\s+)?" + _NUM + r"\s*" + _YRS),
    # "3 years of experience", "2 years relevant industry experience"
    re.compile(_NUM + r"\s*" + _YRS + _GAP + r"\s+(?:experience|exp\b)"),
    # "experience: 2 years", "experience of 3 years", "exp - 1 yr"
    re.compile(r"(?:experience|exp)\s*(?:of|:|-|–|required)?\s*" + _NUM + r"\s*" + _YRS),
    # "3 years or more", "five or more years"
    re.compile(_NUM + r"\s*(?:" + _YRS + r"\s*)?or\s+more\s*" + _YRS + r"?"),
]
_MONTHS = re.compile(r"\b(\d{1,2})\s*(?:\+\s*)?months?\b(?:\s+of)?\s+(?:[\w-]+\s+){0,3}experience")
_FRESHER = re.compile(
    r"\b(freshers?|fresh\s+graduates?|new\s+grads?|entry[- ]level|"
    r"no\s+(?:prior\s+)?experience\s+(?:is\s+)?required|0\s*years?)\b")
_JUNIOR_TITLE = re.compile(
    r"\b(fresher|graduate|new\s+grad|junior|jr\.?|entry[- ]level|trainee|"
    r"apprentice|intern(?:ship)?|sde[\s-]?(?:i|1)|swe[\s-]?(?:i|1)|"
    r"engineer[\s-]?(?:i|1)|associate\s+software)\b(?![\s-]*(?:i{2,}|[2-9]))")

_MAX_SANE = 20  # "our 25 years of history" is not a requirement


def _num(tok):
    tok = tok.lower()
    return _WORDS[tok] if tok in _WORDS else int(float(tok))


def parse_yoe(description, title=""):
    """Headline minimum years required, or None when the posting states none."""
    # the title counts too: "AI Engineer || 7+ Yrs || Pan India"
    text = re.sub(r"\s+", " ", f"{title or ''} \n {description or ''}".lower())
    floors = []
    for pat in _PATTERNS:
        # Blank out each match so a later, looser pattern can't re-read part of
        # it ("1-3 years of experience" must not also yield "3 years ... experience").
        def take(m):
            n = _num(m.group(1))
            if 0 <= n <= _MAX_SANE:
                floors.append(n)
            return " # "
        text = pat.sub(take, text)
    if floors:
        return max(floors)
    if _MONTHS.search(text) or _FRESHER.search(text):
        return 0
    if _JUNIOR_TITLE.search((title or "").lower()):
        return 0
    return None


def classify(yoe_min, yoe_max_allowed=2):
    """'eligible' (stated minimum within range), 'not_stated', or 'too_senior'."""
    if yoe_min is None:
        return "not_stated"
    return "eligible" if yoe_min <= yoe_max_allowed else "too_senior"
