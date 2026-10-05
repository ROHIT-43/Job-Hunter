# Custom Claude Code Skills

## Setup

To enable these skills as slash commands in Claude Code, symlink them:

```bash
cd ~/Desktop/job-hunter   # or wherever you cloned the repo
ln -s "$(pwd)/skills/tailor" ~/.claude/skills/tailor
ln -s "$(pwd)/skills/watchlist" ~/.claude/skills/watchlist
```

## Available Skills

### `/tailor <company | URL>`
Tailors your resume for a specific job posting.

**Prerequisites:**
1. Fill in `data/profile.json` with your candidate profile
2. Place your base resume as `resumes/Base_Resume_<YourName>.tex`

**Usage:**
```
/tailor Techdome                                  # from scored data
/tailor https://linkedin.com/jobs/view/12345      # from any URL
/tailor Techdome eBay Zoca                        # batch mode
```

**Output:** `resumes/<Company>_Resume_<YourFirstName>.tex` — compile on Overleaf.

### `/watchlist [companies...]`
Checks your target companies for openings and scores them against your profile.

**Prerequisites:**
1. Fill in `data/profile.json` with your candidate profile
2. Edit `data/pipeline/target_companies.json` with your dream companies

**Usage:**
```
/watchlist                        # checks all companies in target_companies.json
/watchlist Google Microsoft       # checks only these two
```

**Output:**
- `data/pipeline/target_matches.json` — scored results sorted by match
- `data/pipeline/TARGET_QUEUE.md` — human-readable ranked queue

**Manage your list:**
- "add Stripe to my watchlist"
- "remove Uber from my watchlist"
- "show my watchlist"
