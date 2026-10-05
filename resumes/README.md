# Resumes

This folder holds your base resume and company-tailored versions.

## Setup

1. Place your base LaTeX resume here as `Base_Resume_<YourName>.tex`
2. Make sure `data/profile.json` has your candidate profile filled in
3. Symlink the tailor skill (one-time): `ln -s "$(pwd)/../skills/tailor" ~/.claude/skills/tailor`

## Usage

```
/tailor Google
/tailor Google Microsoft eBay    # batch mode
```

Output: `<Company>_Resume_<YourFirstName>.tex` — compile on [Overleaf](https://www.overleaf.com).

## Files

| File | What |
|------|------|
| `Base_Resume_*.tex` | Your base resume (source of truth, gitignored) |
| `<Company>_Resume_*.tex` | Tailored resumes (gitignored) |
| `README.md` | This file (tracked) |

All `.tex` and `.pdf` files are gitignored since they contain personal data.
