import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("demo", Path(__file__).resolve().parents[1] / "scripts/build_demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class DemoTests(unittest.TestCase):
    def test_scenarios_detected_and_reproducible(self):
        self.assertEqual(demo.build_demo(), demo.build_demo())
        self.assertEqual(len(demo.build_demo()["scenarios"]), 4)

    def test_shared_control_counts_companies_not_paths(self):
        edges = [{"source": "a", "target": "b", "type": "controls"}] * 2
        self.assertEqual(demo.shared_controllers(edges), {})

    def test_cycle_terminates_and_deduplicates_rotations(self):
        graph = {"a": {"b"}, "b": {"c"}, "c": {"a"}, "isolated": set()}
        self.assertEqual(demo.cycles(graph), [("a", "b", "c")])
        self.assertEqual(demo.reachable(graph, "a"), {"b", "c"})
        self.assertEqual(demo.reachable(graph, "isolated"), set())

    def test_converging_paths_do_not_duplicate_exposure(self):
        loans = demo.build_demo()["scenarios"][-1]["loans"]
        self.assertEqual(demo.metrics(loans + loans), demo.metrics(loans))
        self.assertEqual(demo.metrics(loans)["exposure_mxn"], 1650000)

    def test_conflicting_balances_fail(self):
        loan = demo.build_demo()["scenarios"][0]["loans"][0]
        other = dict(loan, amount_mxn=1)
        with self.assertRaises(ValueError):
            demo.metrics([loan, other])

    def test_borrowers_identified_by_id_not_display_name(self):
        loan = demo.build_demo()["scenarios"][0]["loans"][0]
        other = dict(loan, id="another-loan", borrower_id="another-borrower")
        self.assertEqual(demo.metrics([loan, other])["borrower_count"], 2)

    def test_dangling_relationship_fails(self):
        data = copy.deepcopy(demo.build_demo())
        data["scenarios"][0]["edges"][0]["target"] = "missing"
        with self.assertRaises(AssertionError):
            demo.validate(data)


if __name__ == "__main__":
    unittest.main()
