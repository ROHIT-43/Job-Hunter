# job-hunter — project instructions

This repo tailors Rohit Saini's resume to specific job descriptions. These rules are
authoritative and portable (they apply on any machine that clones this repo).

## Resume tailoring — MANDATORY procedure

When the user runs `/tailor` (or asks to tailor/customize/adapt a resume for a job):

1. **Read the rules first.** Before doing anything else, READ
   `.claude/skills/tailor/SKILL.md` in full and follow every rule in it (Steps 0–5,
   the numbered rules, the Relevance hierarchy, the Final tailoring validation, and
   the Core principle). This file is the single source of truth for the tailoring
   procedure. Do not tailor from memory — re-read it each time.
   (`skills/tailor/SKILL.md` is a symlink to the same file.)

2. **Pick the base resume by JD type** (classify the JD first):
   - **Backend JD** → tailor from `resumes/Base_Resume_Rohit.tex`
   - **Frontend JD** → tailor from `resumes/Frontend_Resume_Rohit.tex`
   - **Full-stack JD** → draw from BOTH bases (combine relevant frontend + backend
     content; the frontend base's Frontend/Backend skills split is a good skeleton).

3. **`data/profile.json` is the source of truth for what Rohit actually has.**
   - `skills` = genuinely held. `gap_skills` = NOT held — never claim these unless
     they appear in an experience/project bullet.
   - When a base resume lists a skill that `profile.json` marks as a gap, the
     truthfulness rules win → **drop it**. (Current gaps include Spring Boot,
     Oracle, Kafka, Go, Rust, GraphQL, Next.js, Vue — never claim these even if a
     base or the JD lists them. Check `data/profile.json` `gap_skills` each time,
     as it changes.)

4. **Preserve wording faithfully.** Change emphasis, ordering, and terminology — not
   the underlying facts. Do not inflate the verb or scope of a bullet (e.g. the
   base says "Designed a cross-platform Driver Cancellation…" — do NOT rewrite it to
   "Owned … across design, development, testing, deployment"; that overstates
   ownership and invents responsibilities). See rules 13, 19, 20 in SKILL.md.

5. **Final validation + 1-page check before delivering.** Run the "Final tailoring
   validation" checklist from SKILL.md, then compile the tailored `.tex` with
   `tectonic` and confirm it is exactly **1 page**. Never deliver a 2-page resume.
   Output `.tex` only — the user compiles the PDF on Overleaf.

## Other working preferences

- **Ask before browser automation** (driving the user's Chrome). `WebFetch` /
  `WebSearch` are server-side and exempt.
- Output filename convention: `resumes/<Company>_Resume_Rohit.tex`.
- Do not change LaTeX template code (preamble, packages, margins, commands, spacing)
  or the resume heading — copy them exactly from the chosen base.
