# Scoring methodology

`scripts/rank_jobs.py` gives every job a transparent 0–100 score so the user can
trust and adjust the ordering. The score is a weighted sum of six components.

| Component | Weight | What it measures |
|---|--:|---|
| skills | 45 | Overlap with `must_have_skills` (75%) and `nice_to_have_skills` (25%) found in title/tags/description |
| title | 20 | Role-family match against `target_titles` + seniority within ±1 level |
| location | 15 | Satisfies remote-only / visa-required / preferred locations |
| recency | 10 | Newer postings score higher (≤3d=1.0, ≤7d=0.85, ≤14d=0.65, ≤30d=0.4) |
| salary | 5 | Salary info present |
| company | 5 | `prefer_companies` boost, `avoid_companies` zero-out |

The report prints the component breakdown for the top 10 so it's clear *why*
each role ranked where it did.

## Tuning

- Raise the `skills` weight to be stricter about stack fit.
- Set `remote_only: true` to zero out on-site roles via the location component.
- Set `visa_required: true` to push known visa-sponsoring roles to the top
  (only Arbeitnow reliably flags this; unknown visa status is treated as neutral,
  not disqualifying, so good roles aren't lost).
- `seniority_level` is 0–6 (intern→principal). Jobs more than one level away are
  penalised on the title component but not removed.

## Profile schema

See `assets/profile.example.json`. Build the profile from the user's resume when
available (the `resume-builder` skill already has their stack) rather than asking
them to retype it.
