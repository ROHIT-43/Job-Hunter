"""Executable spec for the seniority-by-title rule in pre_filter.

The rule (USER PREFERENCE, 2026-08-27): the triage drops by TITLE all senior-tier
titles — Senior / Sr / Lead / Principal / Staff / Architect / Distinguished /
Fellow — plus pure management (Manager / Director / VP / Head / Chief). The
candidate is ~1.3 YoE targeting 0-2y and does not want senior-tier roles in the
queue. This OVERRIDES the earlier "score Senior on merit" design.
Level numerals (II / III) are STILL kept (often mid-level, not senior).
"Member of Technical Staff" (an MTS target title) must survive despite "Staff".
See references/backbone.md "Seniority gating" and the drop-senior-titles memory.
"""
import os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from pipeline import pre_filter  # noqa: E402


def keep(title, desc=""):
    ok, reason = pre_filter.is_relevant({"title": title, "description": desc, "company": "Acme Corp"})
    return ok, reason


class TestSeniorDropped(unittest.TestCase):
    """Senior / Sr are title-dropped (2026-08-27 user preference)."""

    def test_senior_software_engineer_dropped(self):
        ok, _ = keep("Senior Software Engineer")
        self.assertFalse(ok)

    def test_sr_swe_dropped(self):
        ok, _ = keep("Sr. Software Engineer")
        self.assertFalse(ok)

    def test_senior_backend_engineer_dropped(self):
        ok, _ = keep("Senior Backend Engineer")
        self.assertFalse(ok)


class TestLevelsAndMtsKept(unittest.TestCase):
    """Level-numerals (II/III) stay; plain MTS survives the Staff kill."""

    def test_software_engineer_levels_kept(self):
        for t in ("Software Engineer II", "Software Engineer III", "SDE II"):
            self.assertTrue(keep(t)[0], f"{t} should be kept")

    def test_member_of_technical_staff_kept(self):
        # MTS is a target title — the "Staff" token must not kill it.
        for t in ("Member of Technical Staff",
                  "Member of Technical Staff - II"):
            self.assertTrue(keep(t)[0], f"{t} should be kept")

    def test_senior_mts_dropped(self):
        # "Senior" now kills even an MTS title.
        self.assertFalse(keep("Senior Member of Technical Staff")[0])


class TestSeniorityTitlesDropped(unittest.TestCase):
    """Lead / Principal / Staff / Architect → dropped by title."""

    def test_lead_dropped(self):
        for t in ("Lead Engineer", "Tech Lead", "Delivery Lead", "Engineering Lead"):
            self.assertFalse(keep(t)[0], f"{t} should be dropped")

    def test_principal_dropped(self):
        self.assertFalse(keep("Principal Software Engineer")[0])

    def test_staff_level_dropped(self):
        for t in ("Staff Engineer", "Staff Software Engineer", "Staff SDE"):
            self.assertFalse(keep(t)[0], f"{t} should be dropped")

    def test_architect_dropped(self):
        self.assertFalse(keep("Solution Architect")[0])


class TestManagementDropped(unittest.TestCase):
    def test_management_titles_dropped(self):
        for t in ("Engineering Manager", "Director of Engineering", "VP Engineering"):
            self.assertFalse(keep(t)[0], f"{t} should be dropped")


class TestYoECoarseNet(unittest.TestCase):
    """pre_filter is the coarse pre-fetch net (>6). The fine >threshold gate
    lives in yoe_split — a Senior role stating 4-5 yrs is kept HERE and excluded
    THERE, never title-purged."""

    def test_seven_plus_years_dropped(self):
        ok, reason = keep("Software Engineer", "Requires 8+ years of experience")
        self.assertFalse(ok)

    def test_plain_swe_kept_by_coarse_net(self):
        # a non-senior title with no stated years passes the coarse net.
        ok, _ = keep("Software Engineer", "3 years of experience preferred")
        self.assertTrue(ok)


class TestWholeWordTitleKills(unittest.TestCase):
    """Bad-title tokens match whole words only (substring matching once killed
    "Chrome" for "hr", "Vector" for "cto", "VPN" for "vp")."""

    def test_no_substring_false_positives(self):
        for t in ("Software Engineer, Chrome", "Vector Search Engineer", "SDE - VPN",
                  "Backend Engineer (Three.js)", "Software Engineer - Factory Automation"):
            self.assertTrue(keep(t)[0], f"{t} should be kept")

    def test_real_tokens_still_kill(self):
        for t in ("HR Executive", "VP Engineering", "Software Engineer, AVP",
                  "(IND) STAFF, DATA ENGINEER", "Staff Machine Learning Engineer"):
            self.assertFalse(keep(t)[0], f"{t} should be dropped")


class TestConfigurableTitleRules(unittest.TestCase):
    """The hourly pipeline passes its own lists from live_config.json."""

    def test_custom_lists(self):
        ok = pre_filter.title_ok
        self.assertTrue(ok("Software Engineer III", ["senior"], [])[0])
        self.assertFalse(ok("Software Engineer III", ["senior", "iii"], [])[0])
        self.assertTrue(ok("Tech Lead", ["senior"], [])[0])          # "lead" removed from list
        self.assertFalse(ok("Member of Technical Staff", ["staff"], [])[0])
        self.assertTrue(ok("Member of Technical Staff", ["staff"], ["member of technical staff"])[0])
        self.assertTrue(ok("Anything", [], [])[0])                   # empty list keeps all


if __name__ == "__main__":
    unittest.main()
