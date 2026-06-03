# Path C — Keyless (public APIs + ToS-safe links)

The free path: live data from sources with clean public APIs, plus pre-filtered
browse links for sites that forbid scraping. No login, no credits. Produces
normalized candidates (already carrying JD text), then hands off to
`references/backbone.md` (writes `APPLY_QUEUE.md`).

## Step 1 — Live fetch (Tier 1)

```bash
python scripts/fetch_jobs.py \
    --departments software,engineering,technology \
    --since-days <ceil(cfg.window_hours / 24), min 1> \
    --adzuna-country in --adzuna-id "$ADZUNA_ID" --adzuna-key "$ADZUNA_KEY" \
    --out jobs.json
```

Jobs are kept by **department**, not keyword. One run sweeps India + remote + visa.
Add `--remote` and/or `--visa` to hard-filter. Omit the Adzuna flags to skip it
(free key from developer.adzuna.com unlocks the strongest India source). Map
`cfg["target_titles"]` to the relevant departments.

## Step 2 — Browse links (Tier 2)

```bash
python scripts/search_urls.py \
    --keywords "backend engineer haskell rust" \
    --location "Bengaluru" --remote --since-days 7 \
    --category general,tech --out search_links.md
```

ToS-safe deep links grouped by `--category` (general, tech, remote, freshers,
bluecollar, freelance, all). Match the category to the candidate's level.

## Step 3 — Hand to the backbone

Candidates already carry JD text, so scoring uses `scripts/score_jobs.py`
(dictionary ATS + optional LLM required-vs-preferred re-weight; see
`references/scoring.md`). Then run `references/backbone.md` (dedup → red-flag →
YoE split → persist + queue). Writes `data/pipeline/APPLY_QUEUE.md`.
