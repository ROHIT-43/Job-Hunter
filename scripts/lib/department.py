"""Department taxonomy: classify a job into engineering-family departments and
map departments to per-source native search facets.

The taxonomy lives in assets/departments.json so it is tunable without code
changes. Keys starting with "_" are control entries (e.g. "_deny"), not
departments.
"""
import json
import re

from lib import paths

_TAXONOMY = None


def load_taxonomy(path=None):
    """Load (and cache) the taxonomy dict from assets/departments.json."""
    global _TAXONOMY
    if path is None and _TAXONOMY is not None:
        return _TAXONOMY
    with open(path or paths.asset("departments.json")) as f:
        tax = json.load(f)
    if path is None:
        _TAXONOMY = tax
    return tax


def _departments(tax):
    return {k: v for k, v in tax.items() if not k.startswith("_")}


def default_departments(tax=None):
    tax = tax or load_taxonomy()
    return [k for k, v in _departments(tax).items() if v.get("default_on")]


def _hay(title, tags):
    return (title or "").lower() + " " + " ".join(tags or []).lower()


def _word_hit(needle, hay):
    # Match whole tokens/phrases so "qa" doesn't fire inside "quality".
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])",
                     hay) is not None


def classify(title, tags=None, tax=None):
    """Return the set of department keys whose matchers hit title/tags.

    A global "_deny" list short-circuits the whole job (e.g. "sales engineer").
    """
    tax = tax or load_taxonomy()
    hay = _hay(title, tags)
    for bad in tax.get("_deny", []):
        if _word_hit(bad, hay):
            return set()
    hits = set()
    deps = _departments(tax)
    for dept, cfg in deps.items():
        if any(_word_hit(m, hay) for m in cfg.get("title_match", [])):
            hits.add(dept)
    # A specialized bucket (data/devops/security/qa — anything not default-on)
    # suppresses the broad generic buckets, so a "Data Engineer" classifies as
    # data, not engineering. This keeps the default net (software/engineering/
    # technology) clear of roles that belong to an opt-in bucket.
    generic = {k for k, v in deps.items() if v.get("default_on")}
    specialized = set(deps) - generic
    if hits & specialized:
        hits -= generic
    return hits


def matches(job, selected, tax=None):
    """(kept?, assigned_departments) for a job against the selected set."""
    depts = classify(job.get("title", ""), job.get("tags"), tax)
    return bool(depts & set(selected)), depts


def facet_codes(selected, source, tax=None):
    """Sorted union of native facet codes for `source` across selected depts."""
    tax = tax or load_taxonomy()
    deps = _departments(tax)
    codes = set()
    for d in selected:
        codes |= set(deps.get(d, {}).get("facets", {}).get(source, []))
    return sorted(codes)
