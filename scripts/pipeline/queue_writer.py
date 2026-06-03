#!/usr/bin/env python3
"""
queue_writer.py — Render the two-section (Primary / Stretch) match queue markdown.

Primary = roles within the candidate's YoE; Stretch = roles whose JD states a
minimum above the threshold (kept for visibility + dedup, out of the main list).
"""


def render_entry(m: dict, show_yoe: bool = False) -> str:
    yoe = ""
    if show_yoe:
        label = m.get("yoe_label") or (f"min {m['min_yoe']} yrs" if m.get("min_yoe") else "4+ yrs")
        yoe = f"\n**Min YoE:** {label}"
    return (
        f"#### [{m['score']}] {m['title']} — {m['company']}\n"
        f"**Apply:** {m['url']}  |  **JobId:** {m['id']}{yoe}\n"
        f"**Resume:** {m.get('resume_pdf', 'N/A')}\n"
        f"**Strengths:** {', '.join(m.get('matched_skills', []))}\n"
        f"**Gaps:** {', '.join(m.get('gap_skills', []))}\n"
        f"> {m.get('jd_summary', '')}\n"
        f"- [ ] Applied"
    )


def _section(title: str, items, show_yoe: bool) -> str:
    if not items:
        return f"### {title}\n\n_none_\n"
    body = "\n\n".join(render_entry(m, show_yoe) for m in items)
    return f"### {title}\n\n{body}\n"


def render_queue(run_label: str, primary, stretch, scored_n: int, cand_n: int,
                 threshold: int = 3) -> str:
    """Render the queue with ONLY Primary (min YoE <= threshold / no stated min).

    Stretch roles (stated minimum > threshold) are NEVER listed or tailored — they
    are tracked in seen_jobs.json for dedup only. We just note how many were
    excluded so the funnel stays transparent.
    """
    header = (
        f"## Hunt — {run_label} — {len(primary)} matches (min YoE <= {threshold}) "
        f"/ {scored_n} scored / {cand_n} candidates\n"
    )
    pri = _section("Matches — within YoE / no stated minimum", primary, False)
    note = (
        f"\n> {len(stretch)} role(s) stating a minimum above {threshold} yrs were "
        f"excluded from this queue (tracked in seen_jobs for dedup, not tailored).\n"
    )
    return f"{header}\n{pri}{note}\n---\n"
