#!/usr/bin/env python3
"""merge_sources.py — merge the keyword pull and the department pull into one
normalized job list, deduped by LinkedIn jobId. Keeps JD text (needed for
scoring) and carries the real companyEmployeesCount from the dept pull.

Sources:
  data/linkedin_export.json  — keyword scrape (raw curious_coder schema, 1000)
                                == the "old 1000" in ats_full_report == the CSV
  data/linkedin_dept.json    — department scrape (richer schema, has
                                companyEmployeesCount + seniorityLevel, 269)

Output: data/linkedin_merged.json (normalized, jobId-deduped).
"""
import json, re, sys

JID = re.compile(r'-(\d{6,})(?:\?|$)')


def jid_from_url(u):
    if not u:
        return None
    m = JID.search(u) or re.search(r'(\d{6,})', u)
    return m.group(1) if m else None


def remote_of(blob):
    b = blob.lower()
    return ("remote" in b) or ("work from home" in b)


def norm_keyword(r):
    """raw curious_coder keyword-pull row -> normalized."""
    jid = str(r.get("jobId") or jid_from_url(r.get("jobUrl")) or "")
    desc = r.get("jobDescription") or ""
    return {
        "id": jid, "source": "linkedin-keyword",
        "title": r.get("jobTitle") or "",
        "company": r.get("companyName") or "",
        "location": r.get("location") or "",
        "remote": remote_of(" ".join([str(r.get("location", "")),
                                      str(r.get("workType", "")), desc[:400]])),
        "visa_sponsorship": None,
        "tags": [t for t in [r.get("contractType"), r.get("experienceLevel")]
                 if t and t != "Not Applicable"],
        "salary": (r.get("salaryInfo") if r.get("salaryInfo") not in ("[]", "", None) else None),
        "description": desc,
        "url": r.get("jobUrl") or r.get("applyUrl") or "",
        "posted": (r.get("publishedAt") or "")[:10] or None,
        "sector": r.get("sector") or "",
        "employees_real": None,
        "seniority": r.get("experienceLevel") or "",
    }


def norm_dept(r):
    """richer department-pull row -> normalized."""
    url = r.get("link") or r.get("applyUrl") or ""
    jid = str(r.get("id") or jid_from_url(url) or "")
    desc = r.get("descriptionText") or ""
    inds = r.get("industries")
    sector = ", ".join(inds) if isinstance(inds, list) else (inds or "")
    wt = r.get("workplaceTypes") or []
    ec = r.get("companyEmployeesCount")
    try:
        ec = int(str(ec).replace(",", "")) if str(ec).strip() not in ("", "None") else None
    except Exception:
        ec = None
    return {
        "id": jid, "source": "linkedin-dept",
        "title": r.get("title") or "",
        "company": r.get("companyName") or "",
        "location": r.get("location") or "",
        "remote": ("Remote" in wt) or remote_of(desc[:400]),
        "visa_sponsorship": None,
        "tags": [t for t in [r.get("employmentType"), r.get("seniorityLevel")]
                 if t and t != "Not Applicable"],
        "salary": r.get("salary") or None,
        "description": desc,
        "url": url,
        "posted": (r.get("postedAt") or "")[:10] or None,
        "sector": sector,
        "employees_real": ec,
        "seniority": r.get("seniorityLevel") or "",
    }


def main():
    out = {}
    stats = {"keyword": 0, "dept": 0, "dupes": 0, "no_id": 0}

    for r in json.load(open("data/linkedin_export.json")):
        j = norm_keyword(r)
        if not j["id"]:
            stats["no_id"] += 1; continue
        if j["id"] in out:
            stats["dupes"] += 1; continue
        out[j["id"]] = j; stats["keyword"] += 1

    for r in json.load(open("data/linkedin_dept.json")):
        j = norm_dept(r)
        if not j["id"]:
            stats["no_id"] += 1; continue
        if j["id"] in out:
            # already have it from keyword pull; enrich with real headcount.
            if j["employees_real"] is not None:
                out[j["id"]]["employees_real"] = j["employees_real"]
            stats["dupes"] += 1; continue
        out[j["id"]] = j; stats["dept"] += 1

    merged = list(out.values())
    json.dump(merged, open("data/linkedin_merged.json", "w"), indent=2, ensure_ascii=False)
    print(f"merged unique jobs: {len(merged)}")
    print(f"  from keyword/CSV: {stats['keyword']} | new from dept: {stats['dept']} | "
          f"jobId dupes dropped: {stats['dupes']} | no-id skipped: {stats['no_id']}")
    print(f"  with real employee count: {sum(1 for j in merged if j['employees_real'] is not None)}")


if __name__ == "__main__":
    main()
