import os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from pipeline import queue_writer  # noqa: E402


def _m(i, score, stretch=False, min_yoe=None):
    return {
        "id": i, "score": score, "title": f"Role {i}", "company": f"Co {i}",
        "url": f"https://www.linkedin.com/jobs/view/{i}",
        "resume_pdf": f"/x/{i}/resume.pdf",
        "matched_skills": ["go", "react"], "gap_skills": ["cassandra"],
        "jd_summary": "summary", "stretch": stretch, "min_yoe": min_yoe,
    }


class TestRenderQueue(unittest.TestCase):
    def setUp(self):
        self.primary = [_m("1", 84), _m("2", 72)]
        self.stretch = [_m("3", 82, stretch=True, min_yoe=4)]
        self.md = queue_writer.render_queue(
            "browser 5h (run X)", self.primary, self.stretch,
            scored_n=200, cand_n=210, threshold=3)

    def test_has_matches_section(self):
        self.assertIn("### Matches", self.md)

    def test_no_stretch_section(self):
        # Stretch roles must NOT be listed in the queue (dedup-only)
        self.assertNotIn("### Stretch", self.md)

    def test_header_counts_primary_only(self):
        self.assertIn("2 matches", self.md)

    def test_stretch_excluded_note(self):
        # the 1 stretch role is noted as excluded, not listed
        self.assertIn("1 role(s) stating a minimum above 3 yrs were excluded", self.md)

    def test_stretch_entries_absent(self):
        # the stretch job's id must not appear anywhere in the queue
        self.assertNotIn("**JobId:** 3", self.md)
        self.assertNotIn("**Min YoE:**", self.md)

    def test_primary_entries_have_apply_and_checkbox(self):
        self.assertIn("**JobId:** 1", self.md)
        self.assertIn("- [ ] Applied", self.md)

    def test_empty_sections_render_placeholder(self):
        md = queue_writer.render_queue("t", [], [], 0, 0, 3)
        self.assertIn("_none_", md)


if __name__ == "__main__":
    unittest.main()
