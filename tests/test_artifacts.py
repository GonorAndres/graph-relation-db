"""Published evidence must match the implementation and keep datasets separate."""
import csv
import hashlib
import json
from pathlib import Path
import unittest

from scripts.build_demo import build_demo

ROOT = Path(__file__).resolve().parents[1]


class ArtifactTests(unittest.TestCase):
    def test_demo_matches_generator(self):
        self.assertEqual(json.loads((ROOT / "web/data/demo.json").read_text()), build_demo())

    def test_model_artifact_is_complete_and_traceable(self):
        data = json.loads((ROOT / "web/data/model-results.json").read_text())
        checksum = hashlib.sha256((ROOT / "scripts/model_experiment.py").read_bytes()).hexdigest()
        self.assertEqual(data["provenance"]["generator_sha256"], checksum)
        self.assertEqual(len(data["runs"]), 15)
        self.assertEqual({r["condition"] for r in data["runs"]}, {"absent", "moderate", "strong"})
        for run in data["runs"]:
            self.assertEqual(sum(s["borrowers"] for s in run["split_counts"].values()), 10000)
            self.assertTrue(all(s["positives"] > 0 for s in run["split_counts"].values()))
            self.assertEqual(len(run["models"]), 4)
            for model in run["models"]:
                for metric, value in model["metrics"].items():
                    self.assertGreaterEqual(value, 0)
                    low, high = model["ci95"][metric]
                    self.assertLessEqual(low, high)
                curve = model["calibration_curve"]
                self.assertEqual(len(curve["predicted"]), len(curve["observed"]))

    def test_published_membership_has_no_group_overlap(self):
        partitions, counts = {}, {}
        with (ROOT / "artifacts/model/split-membership.csv").open() as stream:
            for row in csv.DictReader(stream):
                group_key = row["seed"], row["group_id"]
                self.assertEqual(partitions.setdefault(group_key, row["split"]), row["split"])
                borrower_key = row["seed"], row["borrower_id"]
                self.assertNotIn(borrower_key, counts)
                counts[borrower_key] = 1
        self.assertEqual(len(counts), 50000)
        self.assertEqual(len(partitions), 5000)


if __name__ == "__main__":
    unittest.main()
