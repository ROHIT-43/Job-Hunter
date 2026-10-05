"""salary.py — Salary stated in a posting, parsed to LPA (lakhs per annum, INR).

parse_salary() reads LinkedIn's salary field or JD text ("₹12-18 LPA", "CTC up to
15 lakhs", "₹1,200,000/yr", "₹80K/month"); non-INR amounts are ignored. Jobs that
state no salary get a web-sourced range from salary_lookup.py instead.
"""
import re

_LAKH = 100_000
_MIN_LPA, _MAX_LPA = 1.0, 300.0  # outside this, it's not an annual base salary

_N = r"(\d+(?:\.\d+)?)"
_DASH = r"\s*(?:-|–|—|to)\s*"
_RUPEE = r"(?:₹|rs\.?|inr)"
# 12-18 LPA / 12 to 18 lakhs / 12-18 L
_LPA_RANGE = re.compile(_RUPEE + r"?\s*" + _N + r"\s*(?:l|lpa|lakhs?|lacs?)?" + _DASH +
                        _RUPEE + r"?\s*" + _N + r"\s*(?:lpa|lakhs?|lacs?|l)\b")
# 15 LPA (unambiguous unit)
_LPA_ONE = re.compile(_RUPEE + r"?\s*" + _N + r"\s*lpa\b")
# 15 lakhs — only when salary words are nearby ("10 lakh users" is not pay)
_LAKH_ONE = re.compile(_RUPEE + r"?\s*" + _N + r"\s*(?:lakhs?|lacs?)\b(?:\s*(?:per annum|p\.?\s?a\.?))?")
_CR = re.compile(_N + r"(?:" + _DASH + _N + r")?\s*(?:cr|crores?)\b")
# ₹1,200,000.00/yr - ₹1,800,000.00/yr  |  ₹80K/month  |  INR 10,00,000 - 15,00,000
_AMOUNT = r"(\d[\d,]*(?:\.\d+)?)\s*(k)?"
_PERIOD = r"(?:\s*(?:/|per)\s*(yr|year|annum|month|mo))?"
_RUPEE_AMT = re.compile(_RUPEE + r"\s*" + _AMOUNT + _PERIOD +
                        r"(?:" + _DASH + _RUPEE + r"?\s*" + _AMOUNT + _PERIOD + r")?")
_PAY_WORDS = re.compile(r"\b(salary|ctc|package|compensation|pay|budget|lpa|per annum|"
                        r"remuneration|stipend|offer)\b")


def _sane(lo, hi):
    if lo is None:
        return None
    hi = hi if hi is not None else lo
    if hi < lo:
        lo, hi = hi, lo
    if _MIN_LPA <= lo and hi <= _MAX_LPA:
        return round(lo, 1), round(hi, 1)
    return None


def _rupees_to_lpa(num, k, period):
    v = float(num.replace(",", "")) * (1000 if k else 1)
    if period in ("month", "mo"):
        v *= 12
    return v / _LAKH


def parse_salary(text):
    """(min_lpa, max_lpa) found in `text`, or None."""
    t = re.sub(r"\s+", " ", (text or "").lower())
    if not t:
        return None
    m = _LPA_RANGE.search(t)
    if m:
        return _sane(float(m.group(1)), float(m.group(2)))
    m = _CR.search(t)
    if m and _PAY_WORDS.search(t[max(0, m.start() - 60):m.end() + 30]):
        lo = float(m.group(1)) * 100
        return _sane(lo, float(m.group(2)) * 100 if m.group(2) else None)
    m = _LPA_ONE.search(t)
    if m:
        return _sane(float(m.group(1)), None)
    for m in _LAKH_ONE.finditer(t):
        if _PAY_WORDS.search(t[max(0, m.start() - 60):m.end() + 30]):
            return _sane(float(m.group(1)), None)
    for m in _RUPEE_AMT.finditer(t):
        lo_num, lo_k, lo_p, hi_num, hi_k, hi_p = m.groups()
        period = lo_p or hi_p
        lo = _rupees_to_lpa(lo_num, lo_k, period)
        hi = _rupees_to_lpa(hi_num, hi_k, hi_p or period) if hi_num else None
        got = _sane(lo, hi)
        if got:
            return got
    return None


def bucket(lo, hi, edges=(10, 20)):
    """'0-10' / '10-20' / '20+' by range midpoint."""
    mid = (lo + hi) / 2
    if mid < edges[0]:
        return f"0-{edges[0]}"
    if mid < edges[1]:
        return f"{edges[0]}-{edges[1]}"
    return f"{edges[1]}+"
