# CreditGraph

**Which apparently separate borrowers should we review together?**

A bilingual portfolio project for risk and data science audiences. Explore four fictional relationship patterns, inspect affected loans, and see the review each pattern would prompt. A separate experiment tests whether graph features improve simulated future-default prediction.

## Run locally

Python 3.12 is the reference environment. Install dependencies once:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/build_showcase.py
.venv/bin/python -m pytest tests -q
python -m http.server 8000 --directory web
```

Open http://localhost:8000. Generated website artifacts and D3 7.9.0 are included: viewing needs no Python packages, database, CDN, analytics, or cloud account. Serve over HTTP rather than opening index.html directly. Dependency installation requires network access; regeneration does not.

The homepage introduces connected borrowers with a shared-owner example and a short glossary. Follow its links to `analysis.html` for the interactive portfolio, model results, and methodology. English/Spanish selection carries between pages.

## Deployment

Merging to `main` runs the validation workflow, deploys the `web/` frontend to the Cloudflare Pages project `graph-relation-db`, and deploys the configured Vercel project. The Pages workflow expects the GitHub Actions secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`; the existing Vercel workflow uses `VERCEL_TOKEN`, `VERCEL_ORG_ID`, and `VERCEL_PROJECT_ID`. The repository currently contains no separate backend service, so Vercel is retained as the deployment target until one is added.

Use `--demo-only` for quick content iteration. The default build regenerates all 15 model runs and 200 group-bootstrap replicates per run. Builders overwrite their generated artifacts deterministically.

## Investigations

| Pattern | Consequence to investigate |
| --- | --- |
| Shared control | Several companies depend on one controller |
| Guarantee chain | Direct guarantees connect to further dependencies |
| Circular guarantees | Support comes from inside the same group |
| Shared company dependency | Shareholders and a company have overlapping exposure |

Every total sums distinct outstanding loan balances in the displayed scenario. It is **connected exposure**, not expected loss, incremental exposure, recoverable protection, or automatic liability. Paths do not transfer liability.

Names, amounts, and relationships are fictional. Curated scenarios demonstrate a method, not discovered empirical findings. Demo totals and model predictions belong to separate populations and must not be combined. Displayed Cypher uses an illustrative English schema, distinct from the historical Spanish schema.

## Modeling experiment

Five fixed seeds generate 10,000 borrowers in 1,000 disconnected guarantee groups. Observation-date financial attributes predict simulated default over the next 12 months. Outcomes combine individual financial stress, an unobserved group shock, and absent/moderate/strong dependence on connected borrowers' observed financial stress.

Compare constant-rate, borrower-only logistic regression, borrower-only LightGBM, and graph-enriched LightGBM. Entire groups enter train/calibration/test partitions (60/20/20). Preprocessing fits on training rows; sigmoid calibration fits on calibration rows. An explicit feature allowlist excludes future outcomes, identities, and hidden simulator variables.

Results include average precision (the reported PR metric), ROC-AUC, Brier score, log loss, calibration curves, positive counts, and 95% intervals from resampling held-out groups. All conditions are reported. The graph feature deliberately matches a simulator mechanism: positive results establish sensitivity to that assumption, not real-world predictive value. The 8% expected event rate is illustrative, not a regulatory benchmark. Group splitting does not test temporal generalization.

Inspect [complete results](web/data/model-results.json), [configuration](artifacts/model/configuration.json), and [split membership](artifacts/model/split-membership.csv). Summary intervals condition on the five fitted runs; they do not capture all possible training-population uncertainty. See [scikit-learn's calibration documentation](https://scikit-learn.org/stable/modules/calibration.html) for evaluation terminology.

## Engineering choices

- Static HTML/CSS/JavaScript, bundled D3, and locally hosted Space Grotesk / IBM Plex Sans keep the demo independent of infrastructure availability. Font licenses are included in `web/fonts/`.
- Versioned JSON supplies graph, table, and totals from one artifact.
- English and Spanish share numerical evidence; keyboard controls, reduced motion, and tables offer alternatives to graph interaction.
- SQL supports recursive traversal and cycle detection. This demonstrates relationship-oriented representation, not SQL impossibility. See [PostgreSQL documentation](https://www.postgresql.org/docs/16/queries-with.html).

Details: [architecture decisions](docs/architecture_decisions.md) and [reproduction process](docs/pipeline_process.md).

## Historical research track

The numbered acquisition scripts, cloud notebooks, Neo4j loaders, executed stress notebook, and original specification record an earlier GLEIF/UK ownership prototype with a synthetic credit layer. Source/raw/clean datasets are absent from this checkout.

The executed notebook preserves historical outputs, not current live measurements. Its counts are not the new website dataset. Original SQL, regulatory, contagion, and calibration claims were overstated and are not adopted here. In particular, the old model classifies contemporaneous status using delinquency features; this does not establish future-default prediction. The rebuilt experiment replaces that claim without reusing its scores. The original specification includes proposed features, not proof of implementation.

Historical cloud loaders are optional and can write to external databases. They are not part of the offline build. No deployment or git action is part of regeneration.
