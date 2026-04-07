# CreditGraph -- Topological Credit Risk Analysis

A credit risk knowledge graph exploring how ownership topology, guarantee chains, and corporate hierarchies create correlated exposure patterns that flat relational models systematically miss.

Built on real public ownership data (GLEIF + UK Companies House) with a synthetic Mexican credit layer on top.

---

## What This Project Explores

Traditional credit risk analysis treats each borrower independently. SQL queries aggregate by entity, by sector, by region -- but never by *connection*. This project investigates what happens when you model credit portfolios as graphs, where relationships between entities are first-class data rather than derived facts from table joins.

**Core question:** What structural risk patterns become visible only when you represent a credit portfolio as a graph?

**Findings:**
- Circular guarantees (A guarantees B, B guarantees A) have no SQL equivalent at arbitrary depth -- Cypher finds them in one pattern match
- Entity-level diversification is an illusion when control is concentrated: 80 companies controlled by 18 persons is not 80 independent risks
- Contagion depth through guarantee chains is unknowable in advance -- SQL requires one JOIN per hop decided at query-write time, Cypher traverses at runtime
- Calibrated default probabilities and graph topology answer different questions: individual PD vs systemic exposure. Neither replaces the other

---

## Architecture

```
UK PSC topology + GLEIF MX entities
        |
        v
  8 Python scripts (data acquisition, subgraph extraction,
  identity mapping, scenario embedding, quality injection)
        |
        v
  5 raw CSVs -- 1,150 records, 127 embedded quality issues
        |
        v
  PySpark ETL on Databricks (validation, FK anti-joins,
  state standardization, conservation checks)
        |
        v
  Clean Parquet + rejected audit table
        |
        v
  LightGBM + Platt calibration (three-way split,
  scale_pos_weight for 4% class imbalance)
        |
        v
  Neo4J AuraDB -- 853 nodes, 726 edges,
  248 loans scored with calibrated PDs
```

---

## Graph Schema

```
(:ClienteIndividual)-[:TIENE_PRESTAMO]->(:Prestamo)
(:Empresa)-[:TIENE_PRESTAMO]->(:Prestamo)
(:ClienteIndividual|Empresa)-[:GARANTIZA]->(:Prestamo)
(:ClienteIndividual)-[:ES_ACCIONISTA_DE]->(:Empresa)
(:ClienteIndividual)-[:ES_DIRECTOR_DE]->(:Empresa)
(:Empresa)-[:ES_SUBSIDIARIA_DE]->(:Empresa)
```

**Why Prestamo is a node, not a relationship property:** A guarantee is a relationship between a guarantor and a *loan*. If the loan is not a node, you cannot attach a guarantee to it. Anything that participates in more than one relationship type must be a node.

---

## Data Strategy

| Layer | Source | What it provides |
|-------|--------|-----------------|
| Ownership topology | UK PSC (real) | Who controls whom, ownership bands (25-50%, 50-75%, 75-100%) |
| Corporate hierarchy | GLEIF API (real) | Mexican company names, RFC codes, parent-child chains |
| Credit layer | Synthetic | Loans, guarantees, defaults -- calibrated to Mexican benchmarks |

Real topology matters because random graph generators cannot replicate the structural patterns (shared directors, nested subsidiaries, concentrated controllers) that make graph queries meaningful. The credit questions can be synthetic without weakening the demonstration because the method transfers: swap the synthetic layer for a real loan book, queries work unchanged.

---

## What I Learned

### PySpark on Databricks
- Lazy evaluation: transformations build a DAG, only actions trigger execution. Catalyst optimizes the full chain before running anything
- Anti-join for FK validation scales where `.isin(collected_list)` does not -- stays distributed, no driver-side collection
- Explicit `StructType` schemas over `inferSchema`: control type coercion, preserve raw values for rejection reporting
- `F.when()` chains instead of UDFs: stays inside the JVM, keeps Catalyst optimization intact
- Serverless compute limitations: `.cache()` and Spark MLlib constructors are blocked by the Py4J security manager

### Credit Scoring and Calibration
- Raw model scores are rankings, not probabilities. A score of 0.6 does not mean 60% default probability
- Platt scaling (logistic regression on model outputs) converts rankings to calibrated probabilities
- Three-way split (train/calibration/test) keeps calibration and evaluation independent -- two-way contaminates one or the other
- `scale_pos_weight` prevents degenerate classifiers at 4% positive rate
- Reliability diagram is the visual proof that calibration worked

### Graph Thinking
- Cypher pattern matching discovers traversal depth at runtime -- no hardcoded JOIN chains
- The same portfolio looks fundamentally different through a graph lens: 80 independent entities become 18 controllers with correlated exposure
- Topological metrics (degree, centrality) complement but do not replace traditional credit metrics (bureau score, DTI). They answer different questions

---

## Project Structure

```
creditgraph-spec.md               -- full architecture spec
data/
  raw/                             -- 5 CSVs with 127 quality issues
  clean/                           -- validated output + rejected records
  source/                          -- raw API downloads, manifests
scripts/
  00_acquire_gleif.py              -- GLEIF API: 7,015 MX entities
  01_acquire_psc.py                -- UK PSC: 600 controllers
  02_extract_subgraph.py           -- NetworkX subgraph extraction
  03_map_to_creditgraph.py         -- Mexican identity mapping
  04_embed_scenarios.py            -- structural risk patterns
  04b_add_gleif_hierarchy.py       -- BBVA, Bimbo, Inbursa groups
  05_embed_quality_issues.py       -- 127 data quality issues
  06_generate_neo4j_load.py        -- clean CSVs + Cypher load scripts
  07_load_neo4j.py                 -- AuraDB batch inserts
notebooks/
  etl_pyspark_creditgraph.py       -- Databricks ETL (PySpark)
  credit_scoring_lightgbm.py       -- LightGBM + Platt calibration
  stress_test_analysis_executed.ipynb -- stress test with live Cypher
neo4j/
  constraints.cypher               -- graph constraints
  load_all.cypher                  -- load scripts
docs/
  architecture_decisions.md        -- 7 decisions in exploratory prose
  pipeline_process.md              -- pipeline documentation
```

---

## Technical Stack

- **Graph database:** Neo4J AuraDB
- **Query language:** Cypher
- **ETL:** PySpark on Databricks
- **ML:** LightGBM + Platt calibration (sklearn)
- **Data acquisition:** GLEIF API, Open Ownership BODS
- **Graph analysis:** NetworkX
- **Languages:** Python

---

## Limitations (Honest Framing)

- The graph topology is simpler than production data. Real Mexican corporate groups have cross-holdings, multi-level nesting, and circular ownership that this dataset does not capture. Real data would have MORE connections, making the graph approach MORE valuable, not less.
- Synthetic credit numbers are not auditable facts. The project demonstrates a method, not a conclusion.
- The GLEIF parent-child layer is a flat tree (one parent, N children, one level deep). Real structures are deeper and messier.
- UK PSC and GLEIF MX have zero entity overlap -- they demonstrate different contagion patterns in separate graph clusters, not one unified connected graph.
