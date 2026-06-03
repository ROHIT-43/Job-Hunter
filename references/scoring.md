# Scoring methodology

> **Two scorers, one contract.** The keyless/Apify paths use the **deterministic**
> dictionary ATS below (`score_jobs.py`/`lib/ats.py`, bounded by construction). The
> **browser path** LLM-scores from full JD text using the canonical rubric in
> **`assets/scoring_rubric.md`** — sent verbatim to every scoring subagent, with a
> schema-bounded `score` (integer 0–100) and **Sonnet-or-better** (Haiku is banned
> for scoring). Both emit the same `{score, min_yoe, matched_skills, gap_skills,
> jd_summary}` shape. `assets/scoring_rubric.md` is the single source of truth for
> LLM scoring.

`scripts/score_jobs.py` (backed by `scripts/lib/ats.py`) gives every job a 0–100
**ATS match**: the share of skills a JD asks for that the candidate already has.

    ATS% = |JD skills ∩ your skills| / |JD skills|

JD skills are master-dictionary terms (`assets/skills_dictionary.json`) found in
the JD text. Ordering is: **qualifying first** (YoE gate, below) → ATS% → company
tier (T1 big tech > T2 renowned startups > neutral > ⚠️ likely <100-dev shop) →
number of matched skills → recency. JDs mentioning fewer than 3 skills are
flagged low-signal and ranked below high-signal roles. Departments are filtered
at fetch time, not here (`assets/departments.json`).

## Strict years-of-experience gate

Before ranking, each job is checked against a hard YoE floor. `extract_min_yoe`
parses the JD's stated minimum ("5+ years", "3-5 years" → 3, "at least 4
years"); if the candidate's `years_experience` is **below** it, the job is
**disqualified** — its score is zeroed, it is marked ⛔ with the reason ("needs
8y, have 3y"), and it sinks below every qualifying role. The gate is a no-op when
either the candidate's YoE or the JD's minimum is unknown (no constraint), so
nothing is dropped silently. This is the one hard filter; everything else is soft
ranking.

## Optional: LLM-weighted required vs preferred

The flat score above weights every JD skill equally. An optional second pass
(SKILL.md step 7) has the model label each shortlisted JD's skills as
**required** or **preferred**, then re-scores:

    weighted ATS% = (w_req·|required ∩ have| + w_pref·|preferred ∩ have|)
                  / (w_req·|required|       + w_pref·|preferred|)

Defaults `w_req = 1.0`, `w_pref = 0.3` (CLI `--w-req` / `--w-pref`). The LLM only
labels JD skills required/preferred; matching against your skills and all
arithmetic stay in `lib/ats.weighted_score`, so the number is deterministic and
auditable given the labels. Re-scored jobs are marked ✨ and their Gaps column
shows missing **required** skills. This is an advisory match, not a prediction of
any ATS accept/reject decision.

## Tuning

- Extend `assets/skills_dictionary.json` (canonical → aliases) so more JD skills
  are detected — this directly improves ATS accuracy.
- Your HAVE skills come from the candidate profile (`skills[]` +
  `experience[].skills[]` + `projects[].skills[]`); keep it complete.
- Company tiers (T1/T2/known-large/red-flag) live in `lib/ats.py`; they only
  break ties between equal-ATS roles.
- Department selection happens at fetch (`fetch_jobs.py --departments …`).

## Profile schema

See `assets/candidate.example.json`. Build the profile from the user's resume
when available (the `resume-builder` skill already has their stack) rather than
asking them to retype it.
