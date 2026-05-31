import csv, json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "score_jobs.py")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "jobs_sample.json")


def csv_rows(path):
    with open(path) as f:
        return list(csv.DictReader(f))


class TestScoreJobsCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.profile = os.path.join(self.tmp, "profile.json")
        with open(self.profile, "w") as f:
            json.dump({"name": "T", "skills": ["python", "kafka",
                       "postgresql", "aws", "go", "kubernetes"]}, f)

    def run_cli(self, *extra):
        return subprocess.run(
            [sys.executable, SCRIPT, FIXTURE, "--profile", self.profile,
             "--out-dir", self.tmp, *extra],
            capture_output=True, text=True)

    def test_dedup_and_report_written(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.tmp, "jobs_ranked.csv")) as f:
            rows = f.read().splitlines()
        # 4 input rows, one (title,company) dup removed -> 3 data rows + header
        self.assertEqual(len(rows), 4)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "report.md")))

    def test_low_signal_sorts_last(self):
        self.run_cli()
        rows = csv_rows(os.path.join(self.tmp, "jobs_ranked.csv"))
        self.assertEqual(rows[-1]["title"], "Engineer")  # the low-signal one

    def test_emit_shortlist(self):
        sl = os.path.join(self.tmp, "shortlist.json")
        self.run_cli("--emit-shortlist", sl, "--shortlist-n", "2")
        with open(sl) as f:
            data = json.load(f)
        self.assertIn("have_skills", data)
        self.assertEqual(len(data["jobs"]), 2)
        self.assertIn("key", data["jobs"][0])
        self.assertIn("description", data["jobs"][0])

    def test_llm_labels_override_and_mark(self):
        # Razorpay job: JD has python,kafka,postgresql,aws,terraform.
        # Label aws+terraform as REQUIRED (candidate lacks terraform),
        # everything else preferred -> weighted score must differ from dict.
        key = "Senior Backend Engineer::Razorpay"
        labels = {key: {"required": ["python", "aws", "terraform"],
                        "preferred": ["kafka", "postgresql"]}}
        lp = os.path.join(self.tmp, "labels.json")
        with open(lp, "w") as f:
            json.dump(labels, f)
        r = self.run_cli("--llm-labels", lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = {row["title"]: row for row in
                csv_rows(os.path.join(self.tmp, "jobs_ranked.csv"))}
        rz = rows["Senior Backend Engineer"]
        self.assertEqual(rz["enriched"], "1")
        # required python,aws,terraform (have python,aws -> 2/3 weight 1),
        # preferred kafka,postgresql (have both -> 2 weight .3):
        # (1*2 + .3*2)/(1*3 + .3*2) = 2.6/3.6 = 72
        self.assertEqual(rz["ats_pct"], "72")
        self.assertEqual(rz["gaps"], "terraform")  # missing required


class TestYoeGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.profile = os.path.join(self.tmp, "profile.json")
        with open(self.profile, "w") as f:
            json.dump({"name": "Y", "years_experience": 3,
                       "skills": ["python", "kafka", "aws"]}, f)
        self.jobs = os.path.join(self.tmp, "jobs.json")
        with open(self.jobs, "w") as f:
            json.dump([
                {"title": "Senior Backend Engineer", "company": "BigCo",
                 "description": "8+ years experience. Python, Kafka, AWS.",
                 "url": "https://x/senior", "posted": "2026-05-28"},
                {"title": "Backend Engineer", "company": "MidCo",
                 "description": "2+ years. Python, Kafka, AWS.",
                 "url": "https://x/mid", "posted": "2026-05-28"},
            ], f)

    def rows(self):
        subprocess.run([sys.executable, SCRIPT, self.jobs, "--profile",
                        self.profile, "--out-dir", self.tmp],
                       capture_output=True, text=True)
        return {r["title"]: r for r in
                csv_rows(os.path.join(self.tmp, "jobs_ranked.csv"))}

    def test_below_min_is_disqualified_and_last(self):
        rows = self.rows()
        senior = rows["Senior Backend Engineer"]   # needs 8y, have 3y
        self.assertEqual(senior["yoe_ok"], "0")
        self.assertEqual(senior["ats_pct"], "0")
        self.assertEqual(senior["jd_min_yoe"], "8")

    def test_meets_min_qualifies(self):
        rows = self.rows()
        mid = rows["Backend Engineer"]              # needs 2y, have 3y
        self.assertEqual(mid["yoe_ok"], "1")
        self.assertGreater(int(mid["ats_pct"]), 0)

    def test_disqualified_sorts_below_qualified(self):
        ordered = subprocess.run(
            [sys.executable, SCRIPT, self.jobs, "--profile", self.profile,
             "--out-dir", self.tmp], capture_output=True, text=True)
        self.assertEqual(ordered.returncode, 0, ordered.stderr)
        titles = [r["title"] for r in
                  csv_rows(os.path.join(self.tmp, "jobs_ranked.csv"))]
        self.assertEqual(titles[-1], "Senior Backend Engineer")


if __name__ == "__main__":
    unittest.main()
