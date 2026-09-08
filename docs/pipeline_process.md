# Reproducing the showcase

```text
fictional fixtures → validated demo.json → graph + loan table
synthetic cohorts → train/calibrate/test → model-results.json → experiment panel
```

## Commands

With Python 3.12 and requirements-dev.txt installed in a virtual environment:

```bash
.venv/bin/python scripts/build_showcase.py
.venv/bin/python -m pytest tests -q
python -m http.server 8000 --directory web
```

The build uses no network or external writes. --demo-only rebuilds the small investigation. Builders overwrite generated artifacts. Serve the site over HTTP.

## Demo builder

scripts/build_demo.py defines four fictional motifs with bilingual explanations. Validation checks unique IDs, endpoints, ownership, balances, shared controllers, chain reachability, cycles, and shareholder hubs. Repeated paths cannot increase exposure.

Balances are integer MXN. Scenarios are independent. Displayed Cypher describes the demo schema and is not executed by the browser.

## Model builder

scripts/model_experiment.py generates 1,000 groups of ten borrowers per seed, ring guarantees, optional extra relationships, standardized financial attributes, and loan balances. Its logistic outcome formula targets 8% expected events, with realized counts varying.

Five seeds run under three network strengths. Whole groups enter 60/20/20 training/calibration/test partitions. Models share partitions and bootstrap samples. All models use calibration data for sigmoid calibration; raw metrics are also retained. The calibrated constant baseline reflects calibration prevalence.

Outputs:

- web/data/model-results.json: formula, configuration, library versions, source hash, 15 runs, raw/calibrated metrics, reliability points, event counts, intervals, and paired graph-minus-borrower LightGBM differences.
- artifacts/model/configuration.json: reproducibility configuration and provenance.
- artifacts/model/split-membership.csv: all borrower/group assignments across five seeds, shared across conditions.

The website summarizes five seeds and identifies the seed of displayed calibration curves. Summary intervals average within-seed whole-group bootstrap draws, conditional on fitted runs, without general training-population uncertainty.

Reproducibility is defined for the pinned environment. Different libraries/platforms can affect numerical outputs. Source checksums identify the generator.

## Historical pipeline

Older numbered scripts acquire public ownership data, map identities, add synthetic credit/quality scenarios, and prepare Neo4j loads. Cloud notebooks depend on missing datasets and account configuration. The loader's minimal CSV validation differs from PySpark cleaning.

The executed stress notebook preserves an earlier run; it is not a current database verification or offline dependency. Its historical SQL, regulatory, and calibration claims are superseded. The original LightGBM target is contemporaneous status, not a future event.
