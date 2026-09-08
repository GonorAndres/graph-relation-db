"""Leakage boundaries and simulator structure, independent of headline scores."""
import unittest

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from scripts.model_experiment import bootstrap, calibrate, feature_matrix, fit_predict, generate, split_groups


class ModelExperimentTests(unittest.TestCase):
    def test_groups_disjoint_and_edges_contained(self):
        data = generate(n_groups=100)
        split = split_groups(data["group_id"], 42)
        groups = {name: set(data["group_id"][rows]) for name, rows in split.items()}
        self.assertEqual([len(groups[k]) for k in ("train", "calibration", "test")], [60, 20, 20])
        self.assertFalse(groups["train"] & groups["calibration"])
        self.assertFalse(groups["train"] & groups["test"])
        self.assertFalse(groups["calibration"] & groups["test"])
        np.testing.assert_array_equal(data["group_id"][data["edges"][:, 0]], data["group_id"][data["edges"][:, 1]])
        self.assertEqual(sum(map(len, split.values())), 1000)

    def test_future_and_hidden_fields_cannot_enter_predictors(self):
        data = generate(n_groups=100)
        before = feature_matrix(data, graph=True)
        for name in ("future_default", "hidden_probability", "hidden_group_shock", "borrower_id", "group_id"):
            data[name] = np.full(1000, 999999)
        data["future_delinquency"] = np.ones(1000)
        np.testing.assert_array_equal(before, feature_matrix(data, graph=True))

    def test_strength_changes_outcomes_not_observed_inputs_or_splits(self):
        absent = generate(n_groups=100, strength=0)
        strong = generate(n_groups=100, strength=1.5)
        np.testing.assert_array_equal(feature_matrix(absent, True), feature_matrix(strong, True))
        self.assertAlmostEqual(absent["hidden_probability"].mean(), 0.08)
        self.assertAlmostEqual(strong["hidden_probability"].mean(), 0.08)
        self.assertFalse(np.array_equal(absent["future_default"], strong["future_default"]))

    def test_seed_reproducibility(self):
        first, second = generate(n_groups=100), generate(n_groups=100)
        for key in first:
            np.testing.assert_array_equal(first[key], second[key])

    def test_graph_features_follow_observed_outgoing_guarantees(self):
        data = generate(n_groups=20)
        stress = (0.85 * data["leverage"] - 0.65 * data["interest_coverage"] - 0.45 * data["cash_buffer"]) / np.sqrt(0.85**2 + 0.65**2 + 0.45**2)
        for borrower in range(200):
            neighbors = data["edges"][data["edges"][:, 0] == borrower, 1]
            self.assertEqual(data["relationship_count"][borrower], len(neighbors))
            self.assertAlmostEqual(data["connected_financial_stress"][borrower], stress[neighbors].mean())

    def test_calibration_uses_only_calibration_outcomes(self):
        prediction = np.linspace(0.02, 0.7, 100)
        y = np.tile([0, 0, 0, 1], 25)
        result = calibrate(y, prediction, prediction[:10])
        self.assertEqual(len(result), 10)
        self.assertTrue(np.all((result > 0) & (result < 1)))
        changed = calibrate(1 - y, prediction, prediction[:10])
        self.assertFalse(np.allclose(result, changed))

    def test_preprocessing_never_fits_held_out_features(self):
        x = np.arange(100, dtype=float).reshape(-1, 1)
        x[60:] += 10000
        y = np.tile([0, 1], 50)
        split = {"train": np.arange(60), "calibration": np.arange(60, 80), "test": np.arange(80, 100)}
        pipeline = make_pipeline(StandardScaler(), LogisticRegression())
        fit_predict(pipeline, x, y, split)
        self.assertAlmostEqual(pipeline[0].mean_[0], x[:60].mean())
        before = pipeline[-1].coef_.copy()
        y[60:] = 1 - y[60:]
        fit_predict(pipeline, x, y, split)
        np.testing.assert_array_equal(before, pipeline[-1].coef_)

    def test_bootstrap_rejects_single_class_outcomes(self):
        with self.assertRaisesRegex(ValueError, "both outcome classes"):
            bootstrap(np.zeros(10), {"constant": np.full(10, 0.1)}, np.arange(10), 42, 20)


if __name__ == "__main__":
    unittest.main()
