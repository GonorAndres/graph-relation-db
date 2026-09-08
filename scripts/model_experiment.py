"""Reproducible synthetic relationship-risk experiment (never real lending evidence)."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import sklearn
from sklearn.calibration import calibration_curve
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
BORROWER_FEATURES = ("leverage", "interest_coverage", "cash_buffer")
GRAPH_FEATURES = ("relationship_count", "guaranteed_exposure", "connected_financial_stress")
CONDITIONS = {"absent": 0.0, "moderate": 0.75, "strong": 1.5}
METRICS = ("average_precision", "roc_auc", "brier", "log_loss")


def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -35, 35)))


def generate(seed=42, n_groups=1000, group_size=10, strength=0.0):
    """All graph edges and allowed predictors exist at observation time t0."""
    if n_groups < 5 or group_size < 3:
        raise ValueError("Need at least five groups and three borrowers per group")
    rng = np.random.default_rng(seed)
    n = n_groups * group_size
    group = np.repeat(np.arange(n_groups), group_size)
    leverage = rng.normal(0, 1, n)
    coverage = rng.normal(0, 1, n)
    cash = rng.normal(0, 1, n)
    stress = (0.85 * leverage - 0.65 * coverage - 0.45 * cash) / np.sqrt(0.85**2 + 0.65**2 + 0.45**2)
    # Ring guarantees ensure each group is connected; optional chords vary degree.
    edges = set()
    for g in range(n_groups):
        start = g * group_size
        for j in range(group_size):
            edges.add((start + j, start + (j + 1) % group_size))
            if rng.random() < 0.35:
                target = (j + int(rng.integers(2, group_size))) % group_size
                edges.add((start + j, start + target))
    edges = np.asarray(sorted(edges))
    balances = rng.lognormal(10, 0.7, n)
    count = np.bincount(edges[:, 0], minlength=n)
    exposure = np.bincount(edges[:, 0], weights=balances[edges[:, 1]], minlength=n)
    neighbor_stress = np.bincount(edges[:, 0], weights=stress[edges[:, 1]], minlength=n) / count
    hidden_group_shock = rng.normal(0, 0.35, n_groups)[group]
    linear = 1.1 * stress + strength * neighbor_stress + hidden_group_shock
    # Fix expected prevalence to 8% per condition, rather than confounding uplift with prevalence.
    low, high = -20.0, 20.0
    for _ in range(80):
        intercept = (low + high) / 2
        if sigmoid(intercept + linear).mean() > 0.08:
            high = intercept
        else:
            low = intercept
    probability = sigmoid(intercept + linear)
    target = (rng.random(n) < probability).astype(int)
    return {
        "leverage": leverage, "interest_coverage": coverage, "cash_buffer": cash,
        "relationship_count": count, "guaranteed_exposure": exposure,
        "connected_financial_stress": neighbor_stress, "group_id": group,
        "borrower_id": np.arange(n), "future_default": target,
        "hidden_probability": probability, "hidden_group_shock": hidden_group_shock,
        "edges": edges, "intercept": intercept,
    }


def feature_matrix(data, graph=False):
    # Explicit allowlist: adding simulator metadata can never add a predictor.
    names = BORROWER_FEATURES + (GRAPH_FEATURES if graph else ())
    return np.column_stack([data[name] for name in names])


def split_groups(group_ids, seed):
    unique = np.unique(group_ids)
    shuffled = np.random.default_rng(seed + 1000).permutation(unique)
    a, b = int(len(unique) * 0.6), int(len(unique) * 0.8)
    return {name: np.flatnonzero(np.isin(group_ids, groups)) for name, groups in
            zip(("train", "calibration", "test"), (shuffled[:a], shuffled[a:b], shuffled[b:]))}


def metrics(y, prediction):
    return {"average_precision": float(average_precision_score(y, prediction)),
            "roc_auc": float(roc_auc_score(y, prediction)),
            "brier": float(brier_score_loss(y, prediction)),
            "log_loss": float(log_loss(y, prediction, labels=[0, 1]))}


def logits(prediction):
    p = np.clip(prediction, 1e-7, 1 - 1e-7)
    return np.log(p / (1 - p)).reshape(-1, 1)


def calibrate(calibration_y, calibration_prediction, test_prediction):
    # This function receives calibration outcomes only, never test outcomes.
    calibration_model = LogisticRegression(C=1e6, max_iter=1000)
    calibration_model.fit(logits(calibration_prediction), calibration_y)
    return calibration_model.predict_proba(logits(test_prediction))[:, 1]


def fit_predict(model, features, outcomes, split):
    """Fit preprocessing and classifier on train rows; predict held-out rows only."""
    model.fit(features[split["train"]], outcomes[split["train"]])
    return (model.predict_proba(features[split["calibration"]])[:, 1],
            model.predict_proba(features[split["test"]])[:, 1])


def bootstrap(y, predictions, groups, seed, repetitions):
    if np.unique(y).size != 2:
        raise ValueError("Bootstrap evaluation requires both outcome classes")
    rng = np.random.default_rng(seed + 2000)
    group_rows = [np.flatnonzero(groups == g) for g in np.unique(groups)]
    samples = {name: {metric: [] for metric in METRICS} for name in predictions}
    accepted = 0
    for _ in range(repetitions * 20):
        rows = np.concatenate([group_rows[i] for i in rng.integers(0, len(group_rows), len(group_rows))])
        if np.unique(y[rows]).size != 2:
            continue
        for name, prediction in predictions.items():
            for metric, value in metrics(y[rows], prediction[rows]).items():
                samples[name][metric].append(value)
        accepted += 1
        if accepted == repetitions:
            break
    if accepted != repetitions:
        raise ValueError("Insufficient valid group bootstrap samples; increase held-out group count")
    return samples


def interval(values):
    return [float(x) for x in np.quantile(values, [0.025, 0.975])]


def run_experiment(output=ROOT / "web/data/model-results.json", artifact_dir=ROOT / "artifacts/model",
                   seeds=(42, 43, 44, 45, 46), n_groups=1000, group_size=10, repetitions=200):
    import lightgbm
    from lightgbm import LGBMClassifier

    runs, summaries, membership = [], [], []
    for condition, strength in CONDITIONS.items():
        condition_runs, condition_bootstraps = [], []
        for seed in seeds:
            data = generate(seed, n_groups, group_size, strength)
            split = split_groups(data["group_id"], seed)
            train, calibration, test = (split[k] for k in ("train", "calibration", "test"))
            y = data["future_default"]
            if any(np.unique(y[rows]).size != 2 for rows in split.values()):
                raise ValueError("Each split must contain both classes; increase dataset size")
            if condition == "absent":
                for name, rows in split.items():
                    membership.extend((seed, int(data["borrower_id"][i]), int(data["group_id"][i]), name) for i in rows)
            parameters = dict(n_estimators=150, learning_rate=0.04, num_leaves=15,
                              min_child_samples=60, reg_lambda=2.0, verbosity=-1,
                              random_state=seed, n_jobs=2, deterministic=True, force_col_wise=True)
            estimators = {
                "constant": None,
                "logistic_borrower": make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, random_state=seed)),
                "lightgbm_borrower": LGBMClassifier(**parameters),
                "lightgbm_graph": LGBMClassifier(**parameters),
            }
            results, predictions = [], {}
            for name, model in estimators.items():
                x = feature_matrix(data, graph=name == "lightgbm_graph")
                if model is None:
                    cal_p = np.full(len(calibration), y[train].mean())
                    raw_p = np.full(len(test), y[train].mean())
                else:
                    cal_p, raw_p = fit_predict(model, x, y, split)
                p = calibrate(y[calibration], cal_p, raw_p)
                predictions[name] = p
                observed, predicted = calibration_curve(y[test], p, n_bins=10, strategy="quantile")
                results.append({"name": name, "raw_metrics": metrics(y[test], raw_p),
                                "metrics": metrics(y[test], p),
                                "calibration_curve": {"predicted": predicted.tolist(), "observed": observed.tolist()}})
            samples = bootstrap(y[test], predictions, data["group_id"][test], seed, repetitions)
            for result in results:
                result["ci95"] = {metric: interval(samples[result["name"]][metric]) for metric in METRICS}
            run = {"condition": condition, "network_strength": strength, "seed": seed,
                   "intercept": float(data["intercept"]), "split_counts": {
                       name: {"borrowers": len(rows), "groups": int(len(np.unique(data["group_id"][rows]))),
                              "positives": int(y[rows].sum())} for name, rows in split.items()}, "models": results}
            runs.append(run)
            condition_runs.append(run)
            condition_bootstraps.append(samples)
            print(f"{condition}: seed {seed} complete", flush=True)
        models = []
        for index, name in enumerate(estimators):
            values = {}
            for metric in METRICS:
                averaged_bootstrap = np.mean([s[name][metric] for s in condition_bootstraps], axis=0)
                values[metric] = {"mean": float(np.mean([r["models"][index]["metrics"][metric] for r in condition_runs])),
                                  "ci95": interval(averaged_bootstrap)}
            models.append({"name": name, "metrics": values})
        uplift = {}
        for metric in METRICS:
            paired = np.mean([np.asarray(s["lightgbm_graph"][metric]) - np.asarray(s["lightgbm_borrower"][metric])
                              for s in condition_bootstraps], axis=0)
            uplift[metric] = {"mean": models[3]["metrics"][metric]["mean"] - models[2]["metrics"][metric]["mean"],
                              "ci95": interval(paired)}
        summaries.append({"condition": condition, "network_strength": strength, "models": models, "graph_uplift": uplift})
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with (artifact_dir / "split-membership.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("seed", "borrower_id", "group_id", "split"))
        writer.writerows(membership)
    document = {
        "schema_version": 1,
        "title": "Synthetic 12-month default experiment",
        "disclaimer": "Entirely fictional data. Results demonstrate simulator assumptions, not validated lending performance. Demo scenarios are a separate dataset.",
        "configuration": {"seeds": list(seeds), "n_borrowers": n_groups * group_size, "n_groups": n_groups,
                          "conditions": [{"name": k, "network_strength": v} for k, v in CONDITIONS.items()],
                          "split": {"train": 0.6, "calibration": 0.2, "test": 0.2}, "bootstrap_repetitions": repetitions,
                          "borrower_features": BORROWER_FEATURES, "graph_features": GRAPH_FEATURES,
                          "lightgbm_parameters": {k: v for k, v in parameters.items() if k != "random_state"},
                          "calibration": "Logistic sigmoid on clipped probability logits; fit only on calibration split"},
        "generating_process": {
            "observation_date": "2025-01-01", "outcome_window": "2025-01-02 through 2026-01-01 (simulated)",
            "formula": "P(default)=sigmoid(intercept + 1.1*financial_stress + network_strength*mean(guaranteed borrowers' observed financial_stress) + hidden_group_shock)",
            "financial_stress": "(0.85*leverage - 0.65*interest_coverage - 0.45*cash_buffer)/sqrt(0.85^2+0.65^2+0.45^2); each attribute independent standard normal",
            "intercept": "Solved per seed and condition to set mean simulated probability to 0.08; realized prevalence varies",
            "hidden_group_shock": "One independent Normal(0,0.35) draw per relationship group; excluded from predictors",
            "graph": "Each disconnected group is a directed guarantee ring with an additional outgoing chord with probability0.35 per borrower. Balances are LogNormal(10,0.7). All graph features precede outcomes.",
            "limitations": "Edges are generated randomly; this is neither causal identification nor an estimate of real default risk. Absent network effects is a negative control. Temporal generalization is not tested by the group split."},
        "provenance": {"generator": "scripts/model_experiment.py", "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       "versions": {"numpy": np.__version__, "sklearn": sklearn.__version__, "lightgbm": lightgbm.__version__},
                       "split_membership": "artifacts/model/split-membership.csv",
                       "uncertainty": "95% percentile intervals from held-out whole-group resampling within each seed. Summary intervals average independent per-seed bootstrap draws; conditional on the five fitted runs, not population or between-training-run uncertainty.",
                       "uplift": "Paired graph-enriched minus borrower-only LightGBM on identical held-out group resamples; positive improves AP/AUC, negative improves Brier/log loss."},
        "summary": summaries, "runs": runs,
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, allow_nan=False) + "\n")
    (artifact_dir / "configuration.json").write_text(json.dumps({k: document[k] for k in ("configuration", "generating_process", "provenance")}, indent=2) + "\n")
    return document


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "web/data/model-results.json")
    parser.add_argument("--artifact-dir", type=Path, default=ROOT / "artifacts/model")
    parser.add_argument("--bootstrap", type=int, default=200)
    args = parser.parse_args()
    if args.bootstrap < 20:
        parser.error("--bootstrap must be at least20")
    run_experiment(args.output, args.artifact_dir, repetitions=args.bootstrap)
