"""Executable spec for the seniority-by-title rule in pre_filter.

The rule (Arnab, 2026-06-04): the triage may drop by TITLE only the
unambiguously-too-senior IC titles — Lead / Principal / Staff / Architect — plus
pure management (Manager / Director / VP / Head / Chief). It must NEVER title-purge
Senior / Sr; those are scored on merit and gated only by the JD-based YoE rule.
"Member of Technical Staff" (an MTS target title) must survive despite "Staff".

If you are an agent tempted to "tidy up" by adding "senior" to the kill list:
DON'T. These tests will fail, and you'll be re-breaking the 2026-06-04 bug.
See references/backbone.md "Seniority gating" and the no-senior-title-purge memory.
"""
import os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from pipeline import pre_filter  # noqa: E402


def keep(title, desc=""):
    ok, reason = pre_filter.is_relevant({"title": title, "description": desc, "company": "Acme Corp"})
    return ok, reason


class TestSeniorKept(unittest.TestCase):
    """Senior / Sr / level-numerals are SCORED, never title-purged."""

    def test_senior_software_engineer_kept(self):
        ok, _ = keep("Senior Software Engineer")
        self.assertTrue(ok)

    def test_sr_swe_kept(self):
        ok, _ = keep("Sr. Software Engineer")
        self.assertTrue(ok)

    def test_senior_backend_engineer_kept(self):
        ok, _ = keep("Senior Backend Engineer")
        self.assertTrue(ok)

    def test_software_engineer_levels_kept(self):
        for t in ("Software Engineer II", "Software Engineer III", "SDE II"):
            self.assertTrue(keep(t)[0], f"{t} should be kept")

    def test_member_of_technical_staff_kept(self):
        # MTS is a target title — the "Staff" token must not kill it.
        for t in ("Member of Technical Staff",
                  "Member of Technical Staff - II",
                  "Senior Member of Technical Staff"):
            self.assertTrue(keep(t)[0], f"{t} should be kept")


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

    def test_four_year_senior_kept_here(self):
        # kept by the coarse net; the >3 fine gate (yoe_split) handles it later.
        ok, _ = keep("Senior Software Engineer", "4 years of experience required")
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
