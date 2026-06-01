#!/usr/bin/env bash
# build_pdfs.sh — compile every applications/*/resume.tex to resume.pdf locally,
# using the real Overleaf project (resume-openfont.cls + Lato/Raleway fonts +
# fontawesome v4) via tectonic. No browser, no clipboard.
#
# Requires: tectonic (brew install tectonic) and the downloaded Overleaf project.
# Usage: bash scripts/build_pdfs.sh
set -euo pipefail

PROJ="${OVERLEAF_PROJECT:-/Users/arnabdutta/Downloads/ArnabDutta}"   # has the real .cls + fonts
APPS="$(cd "$(dirname "$0")/.." && pwd)/data/output/applications"

[ -f "$PROJ/resume-openfont.cls" ] || { echo "ERROR: real resume-openfont.cls not found in $PROJ"; exit 1; }
command -v tectonic >/dev/null || { echo "ERROR: tectonic not installed (brew install tectonic)"; exit 1; }

ok=0; fail=0
for tex in "$APPS"/*/resume.tex; do
  dir="$(dirname "$tex")"; name="$(basename "$dir")"
  cp "$tex" "$PROJ/_build.tex"
  if (cd "$PROJ" && tectonic _build.tex >/dev/null 2>&1); then
    mv "$PROJ/_build.pdf" "$dir/resume.pdf"; echo "  ✓ $name"; ok=$((ok+1))
  else
    echo "  ✗ $name FAILED"; fail=$((fail+1))
  fi
done
rm -f "$PROJ"/_build.*
echo "built $ok, failed $fail"
