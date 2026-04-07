# CreditGraph — Project Specification
**Version 1.0 | Target: VinkOS Data Scientist Role**

---

## What This Document Is

This is not a tutorial. It is the architecture decision record, data specification,
and learning contract for CreditGraph — a credit risk knowledge graph built in Neo4J,
processed with PySpark, scored with a calibrated ML model, and queried with generative AI.

Every section answers a question you will be asked in an interview or in your first week
on the job. Read it once before you write a single line of code.

---

## The Problem This Project Solves

A Mexican financial institution has a credit portfolio of 500 clients.
Some are individuals. Some are companies. Some clients have guaranteed each other's loans —
meaning if Client A defaults, Client B (who guaranteed A's loan) becomes liable.
Some companies share directors. Some individuals are shareholders of companies
that also have loans with the institution.

A traditional relational database sees this as separate tables:
`clientes`, `prestamos`, `garantias`, `empresas`, `directores`.

To answer the question "if Empresa X defaults today, which other clients
are exposed and how much is the total indirect exposure?" in SQL,
you need a recursive CTE that most analysts write incorrectly,
that runs slowly at scale, and that breaks completely when
the guarantee chain has more than 3 levels of depth.

A graph database answers the same question in two lines of Cypher.
More importantly, it answers questions the SQL model cannot even formulate —
like "find all circular guarantee structures in the portfolio"
or "which client is the single point of failure whose default would
trigger the most cascading exposure?"

**This is the exact problem VinkOS is solving for their client right now.**
CreditGraph is a working prototype of that system.

---

## What You Will Be Able to Demonstrate After

These are not learning objectives. They are statements you will make
in the interview, backed by code you wrote.

**On graph databases:**
> "I modeled a credit portfolio as a native graph in Neo4J.
> The schema decision — what becomes a node versus a relationship versus
> a property — has direct consequences for query performance and
> expressiveness. I can explain those decisions and defend them."

**On Cypher:**
> "I wrote Cypher queries for four real credit risk use cases:
> direct exposure, indirect exposure through guarantee chains,
> circular guarantee detection, and default contagion scoring.
> I know where Cypher is more expressive than SQL and where SQL
> is still the right tool."

**On PySpark:**
> "I wrote the ingestion and transformation pipeline in PySpark
> on Databricks, not pandas, because the same code needs to run
> on a distributed cluster in production. I understand lazy evaluation,
> why collect() inside a loop is dangerous, and how partitioning
> affects join performance."

**On MLOps:**
> "Every risk score stored in the graph carries a version tag,
> a model name, and a timestamp. This is not cosmetic.
> In production, when you retrain the model, you need to know
> which nodes were scored with which version and when,
> so you can audit decisions and roll back if the new model
> produces anomalous scores."

**On generative AI + graphs:**
> "The generative AI layer doesn't guess. It reads actual subgraph
> context extracted by Cypher, passes it to the LLM as structured
> text, and generates a natural language answer grounded in real data.
> I know where this breaks — when the subgraph context is too large
> for the context window, or when the question requires aggregation
> that Cypher should handle before passing to the LLM."

**On your actuarial background applied here:**
> "The default probability attached to each client node is a
> calibrated probability, not just a model score.
> The difference matters: an AUC of 0.85 tells you the model
> ranks risk correctly, but calibration tells you whether
> a score of 0.15 actually means 15% probability of default.
> For a risk committee making provisioning decisions,
> calibration is not optional."

---

## The Data

### Why Synthetic and Not a Public Dataset

There is no Mexican equivalent of freMTPL2 for credit risk.
CNBV (Comisión Nacional Bancaria y de Valores) does not publish
granular anonymized loan-level data the way French and UK regulators do.
The closest public option is the UCI Credit Card Default dataset
(Taiwan, 2005) — but it has no graph structure,
no guarantee relationships, no corporate ownership chains.

We generate synthetic data because:

1. We control the graph structure — we can embed
   circular guarantees, guarantee chains of depth 4,
   and companies with multiple individual shareholders
   to make the graph queries non-trivial.

2. We control the default signal — we can calibrate
   the synthetic default rate to a realistic Mexican
   credit portfolio (approximately 3-5% NPL ratio
   for a conservative institutional lender).

3. We control the data quality problems — we embed
   intentional issues (missing values, duplicate clients,
   orphaned relationships) to demonstrate ETL validation
   logic in PySpark.

### The Five Entity Types

The data models five types of entities that mirror what
a real Mexican financial institution would have.

---

#### Entity 1: Clientes Individuales

These are natural persons — individual borrowers.

**Volume:** 300 records

**Fields:**

| Field | Type | Description | Quality Issues Embedded |
|-------|------|-------------|------------------------|
| `id_cliente` | STRING | Unique identifier, format CLI-XXXXX | 5 duplicates with different IDs but same CURP |
| `nombre_completo` | STRING | Full name | 8 records with NULL, 3 records with placeholder "N/A" |
| `curp` | STRING | 18-character Mexican CURP | 4 records with invalid format (wrong length) |
| `fecha_nacimiento` | DATE | Birth date | 2 records with future dates (data entry error), 1 minor (age 16) |
| `estado_residencia` | STRING | Mexican state name | 6 records with NULL, inconsistent naming ("CDMX" vs "Ciudad de Mexico") |
| `nivel_ingresos` | FLOAT | Monthly income in MXN | 3 records with negative values, 12 NULLs |
| `antiguedad_cliente_meses` | INTEGER | Months as client | Range 1-240, no nulls |
| `score_buro` | FLOAT | Credit bureau score 300-850 | 7 records outside valid range |
| `historico_incumplimientos` | INTEGER | Count of past defaults | Range 0-5 |
| `fecha_ultimo_incumplimiento` | DATE | Date of last default if any | NULL when no prior default |

**Why these specific quality issues matter for a credit risk model:**
A negative income value does not fail silently — it inverts
the risk signal. A model trained on data including negative incomes
will learn a spurious pattern. A minor (age 16) in a loan portfolio
is a regulatory violation, not just a data error. A duplicate client
with two IDs means the same person's exposure is counted twice,
understating concentration risk.

---

#### Entity 2: Empresas

These are legal entities — companies with credit exposure.

**Volume:** 80 records

**Fields:**

| Field | Type | Description | Quality Issues Embedded |
|-------|------|-------------|------------------------|
| `id_empresa` | STRING | Unique identifier, format EMP-XXXXX | None — companies are clean by design |
| `razon_social` | STRING | Legal company name | 2 records with NULL |
| `rfc` | STRING | 12-character RFC | 3 records with 13-character RFC (individual format, wrong for company) |
| `sector` | STRING | Economic sector | Categories: MANUFACTURA, COMERCIO, SERVICIOS, CONSTRUCCION, AGRO |
| `tamano` | STRING | Size: MICRO, PEQUENA, MEDIANA, GRANDE | Based on income thresholds |
| `ingresos_anuales_mxn` | FLOAT | Annual revenue in MXN | 4 NULLs, 1 record with zero |
| `anos_operacion` | INTEGER | Years in operation | Range 1-40 |
| `num_empleados` | INTEGER | Employee count | 3 NULLs |
| `estado_registro` | STRING | State of incorporation | Inconsistent with INEGI state codes in 5 records |

---

#### Entity 3: Prestamos

These are loan contracts — the financial exposure at the center of the model.

**Volume:** 450 records (some clients have multiple loans)

**Fields:**

| Field | Type | Description | Quality Issues Embedded |
|-------|------|-------------|------------------------|
| `id_prestamo` | STRING | Unique identifier, format PRE-XXXXX | None |
| `id_titular` | STRING | References id_cliente or id_empresa | 8 orphaned records — the borrower ID doesn't exist |
| `tipo_titular` | STRING | INDIVIDUAL or EMPRESA | Inconsistent with what id_titular resolves to in 3 records |
| `monto_original_mxn` | FLOAT | Original loan amount | 2 NULLs, 1 negative value |
| `saldo_vigente_mxn` | FLOAT | Current outstanding balance | Cannot exceed monto_original_mxn — 5 violations embedded |
| `tasa_interes_anual` | FLOAT | Annual interest rate | Range 0.05-0.45, 3 records with rate above 0.80 (usury flag) |
| `fecha_inicio` | DATE | Loan origination date | 3 records where fecha_inicio > fecha_vencimiento |
| `fecha_vencimiento` | DATE | Maturity date | — |
| `estatus` | STRING | ACTIVO, VENCIDO, PAGADO, REESTRUCTURADO | — |
| `dias_mora` | INTEGER | Days past due | Must be 0 when estatus=ACTIVO — 4 violations |
| `probabilidad_incumplimiento` | FLOAT | PD from the credit model | Range 0-1, filled in Phase 3 |
| `score_version` | STRING | Model version that generated PD | Filled in Phase 3, format "v1.0.0" |
| `score_fecha` | TIMESTAMP | When the score was computed | Filled in Phase 3 |

**The critical field here is `saldo_vigente_mxn`.**
This is the exposure at default for a first-order analysis.
When we propagate risk through the graph, the exposure flowing
through a guarantee relationship is a function of the guarantor's
saldo_vigente, not the original monto. Getting this wrong
means your contagion analysis overstates risk in early-stage loans
and understates it in mature loans near maturity.

---

#### Entity 4: Garantias

These are guarantee relationships — the edges that make the graph interesting.

**Volume:** 180 records (not every loan has a guarantor)

**Fields:**

| Field | Type | Description | Quality Issues Embedded |
|-------|------|-------------|------------------------|
| `id_garantia` | STRING | Unique identifier, format GAR-XXXXX | — |
| `id_prestamo` | STRING | The loan being guaranteed | 5 orphaned — loan ID doesn't exist |
| `id_garante` | STRING | The guarantor (client or company) | 3 orphaned — guarantor ID doesn't exist |
| `tipo_garantia` | STRING | PERSONAL, HIPOTECARIA, PRENDARIA, AVAL | — |
| `cobertura_porcentaje` | FLOAT | Percentage of loan covered by this guarantee | Range 0.25-1.0 |
| `fecha_inicio` | DATE | When guarantee became effective | — |
| `fecha_vencimiento` | DATE | When guarantee expires | 4 records already expired but loan still active |
| `activa` | BOOLEAN | Whether guarantee is currently valid | Inconsistent with fechas in 6 records |

**The `cobertura_porcentaje` field is what makes contagion analysis precise.**
If Client A guarantees 60% of Client B's loan of MXN 500,000,
and Client B defaults, Client A's indirect exposure is MXN 300,000.
A guarantee structure where multiple clients each cover different percentages
of the same loan requires summing their individual exposures correctly —
and requires detecting when the total coverage exceeds 100%,
which is a data quality problem that implies a process failure at the institution.

---

#### Entity 5: Relaciones Empresariales

These are ownership and directorship relationships between
individuals and companies — the second layer of contagion.

**Volume:** 120 records

**Fields:**

| Field | Type | Description | Quality Issues Embedded |
|-------|------|-------------|------------------------|
| `id_relacion` | STRING | Unique identifier, format REL-XXXXX | — |
| `id_individuo` | STRING | The individual (references id_cliente) | 4 orphaned |
| `id_empresa` | STRING | The company (references id_empresa) | 2 orphaned |
| `tipo_relacion` | STRING | ACCIONISTA, DIRECTOR, REPRESENTANTE_LEGAL, APODERADO | — |
| `porcentaje_participacion` | FLOAT | Ownership percentage if ACCIONISTA | NULL for non-shareholders, range 0.01-1.0 |
| `fecha_inicio` | DATE | Start of relationship | — |
| `fecha_fin` | DATE | End of relationship | NULL means currently active |
| `activa` | BOOLEAN | Current status | — |

**Why this entity is critical for credit risk:**
An individual who is a majority shareholder of a company
and has personal loans with the same institution creates
correlated risk. If the company defaults, the individual's
net worth drops, increasing the probability of their personal
default. This is the kind of concentration risk that
relational databases systematically miss and that regulators
increasingly require institutions to monitor and report.

---

### The Embedded Scenarios

The synthetic data is not random — it contains five specific
structural patterns designed to make the graph queries meaningful.

**Scenario 1: Cadena de garantías de profundidad 3**
Client A guarantees the loan of Client B.
Client B guarantees the loan of Client C.
Client C is currently VENCIDO with 45 days of mora.
The question: what is A's total indirect exposure?
In SQL this requires a recursive CTE. In Cypher it is a variable-length path query.

**Scenario 2: Garantía circular**
Client X guarantees the loan of Client Y.
Client Y guarantees the loan of Client Z.
Client Z guarantees the loan of Client X.
This is illegal under Mexican banking regulation (Circular 3/2012 CNBV)
because it creates fictitious coverage — the guarantees cancel each other out.
The question: find all circular guarantee structures in the portfolio.
This query is not possible in standard SQL without recursive CTEs
and is trivial in Cypher.

**Scenario 3: Empresa como nodo central de contagio**
Empresa MANUFACTURA_01 has 3 active loans.
5 individual clients are shareholders of this company.
2 of those individuals have also guaranteed each other's personal loans.
The company is in REESTRUCTURADO status.
The question: map all entities whose financial health is correlated
with Empresa MANUFACTURA_01.

**Scenario 4: Director compartido**
Individual CLI-00089 is director of both Empresa EMP-00012 and Empresa EMP-00031.
Both companies have active loans.
This creates a concentration risk flag: the same person's decisions
affect two separate borrowers. Regulators call this "partes relacionadas."

**Scenario 5: Préstamo sin garantía con alta PD**
15 loans have no guarantor, a PD above 0.25, and are still marked ACTIVO.
These are the unsecured high-risk exposures that a risk manager
needs to identify and provision for immediately.

---

## The Graph Schema

This is the Neo4J data model. Every decision here has a reason.

### Nodes

```
(:ClienteIndividual {
    id_cliente, nombre_completo, curp,
    fecha_nacimiento, estado_residencia,
    nivel_ingresos, score_buro,
    historico_incumplimientos
})

(:Empresa {
    id_empresa, razon_social, rfc,
    sector, tamano, ingresos_anuales_mxn,
    anos_operacion
})

(:Prestamo {
    id_prestamo, monto_original_mxn,
    saldo_vigente_mxn, tasa_interes_anual,
    fecha_inicio, fecha_vencimiento,
    estatus, dias_mora,
    probabilidad_incumplimiento,
    score_version, score_fecha
})
```

### Relationships

```
(:ClienteIndividual)-[:TIENE_PRESTAMO]->(:Prestamo)
(:Empresa)-[:TIENE_PRESTAMO]->(:Prestamo)
(:ClienteIndividual)-[:GARANTIZA {
    cobertura_porcentaje,
    tipo_garantia,
    activa
}]->(:Prestamo)
(:Empresa)-[:GARANTIZA {
    cobertura_porcentaje,
    tipo_garantia,
    activa
}]->(:Prestamo)
(:ClienteIndividual)-[:ES_ACCIONISTA_DE {
    porcentaje_participacion,
    activa
}]->(:Empresa)
(:ClienteIndividual)-[:ES_DIRECTOR_DE {
    activa
}]->(:Empresa)
```

### Why Prestamo is a node and not a relationship property

This is the most important schema decision in the project.

You could model this as:
`(:ClienteIndividual)-[:DEBE {monto, tasa, estatus}]->(:Banco)`

But then a guarantee becomes impossible to model correctly —
a guarantee is a relationship between a guarantor and a loan,
not between two clients. If the loan is not a node,
you cannot attach a guarantee relationship to it.

The moment you need to say "Client A guarantees Loan 102,
which belongs to Client B," the loan must be a node.
This is the fundamental graph modeling insight:
**anything that participates in more than one relationship type
must be a node, not a property.**

---

## The Four Phases — Detailed

### Phase 1: Graph Fundamentals and Schema (Day 1 — 4 hours)

**What you install:**
- Neo4J Desktop (local, free, no account)
- Java 11 (prerequisite)
- Python neo4j driver: `pip install neo4j`

**What you build:**
A Python script `01_generate_data.py` that generates all five entity
CSVs with the embedded quality issues using Faker for Mexican names
and controlled random distributions for financial fields.

A Python script `02_load_graph.py` that connects to the local Neo4J
instance and loads the clean (post-PySpark) data as nodes and relationships.

**The first Cypher challenge:**
Before writing any loading code, draw the graph schema on paper.
Which entities are nodes? Which are relationships?
What properties live on nodes versus relationships?
Defend each decision with one sentence.

**What you learn:**
The mental shift from thinking in tables to thinking in patterns.
A table asks "what does this entity look like?"
A graph asks "how does this entity connect to everything else?"

---

### Phase 2: PySpark ETL Pipeline (Day 1-2 — 5 hours)

**What you build:**
A Databricks notebook `03_etl_pipeline.ipynb` with five cells:

**Cell 1 — Ingest:**
```python
# Read raw CSVs from DBFS (Databricks File System)
# or local path in standalone mode
clientes_raw = spark.read.option("header", True).csv("path/clientes_raw.csv")
prestamos_raw = spark.read.option("header", True).csv("path/prestamos_raw.csv")
# ... same for all five entities
```

**Cell 2 — Validate:**
PySpark native functions only — no UDFs, no pandas.
Flag every data quality problem documented in the data specification above.
Write flagged records to a separate `rejected_records` DataFrame
with a `rejection_reason` column. Do not silently drop them.
An audit trail of what was rejected and why is not optional —
it is the difference between a pipeline and a reliable pipeline.

```python
from pyspark.sql import functions as F

clientes_flagged = clientes_raw.withColumn(
    "rejection_reason",
    F.when(F.col("nivel_ingresos") < 0, "negative_income")
     .when(F.col("score_buro") > 850, "score_out_of_range")
     .when(F.col("score_buro") < 300, "score_out_of_range")
     .when(F.length(F.col("curp")) != 18, "invalid_curp_length")
     .otherwise(None)
)

clientes_clean = clientes_flagged.filter(F.col("rejection_reason").isNull())
clientes_rejected = clientes_flagged.filter(F.col("rejection_reason").isNotNull())
```

**Cell 3 — Transform:**
Standardize state names to INEGI codes.
Cast all date fields to DateType.
Normalize string fields (strip whitespace, uppercase where appropriate).
Resolve the `tipo_titular` inconsistency in prestamos.

**Cell 4 — Integrate:**
Join clientes with prestamos to verify referential integrity.
Identify orphaned loans (id_titular doesn't match any known client or company).
This is where the `id_cliente = 99` problem from the technical test appears in practice.

**Cell 5 — Write:**
Write clean DataFrames to Parquet (not CSV — Parquet preserves schema,
CSV does not). Write a summary report: total records ingested,
records rejected per entity, rejection reasons, timestamp.

**Critical PySpark distinction to internalize:**
In pandas, `df[df['col'] > 0]` executes immediately.
In PySpark, the same filter builds a logical plan.
Nothing touches the data until you call `.show()`, `.count()`,
`.write()`, or `.collect()`.

This means you can chain 20 transformations and Spark will
optimize the entire plan before executing. It also means
that calling `.count()` inside a loop (to check progress)
triggers a full scan on every iteration — a common mistake
that turns a 2-minute job into a 20-minute job.

---

### Phase 3: Credit Risk Scoring (Day 2 — 3 hours)

**What you build:**
A notebook `04_credit_scoring.ipynb` that trains a LightGBM model
on the clean client and loan data, generates calibrated default
probabilities, and writes them back to Neo4J as node properties.

**The features:**
```
score_buro               — direct credit signal
historico_incumplimientos — past behavior predicts future behavior
nivel_ingresos           — repayment capacity
saldo_vigente_mxn        — absolute exposure
tasa_interes_anual       — higher rates often indicate higher risk
dias_mora                — current delinquency signal
antiguedad_cliente_meses — relationship depth (longer = lower risk typically)
```

**The target:**
`label = 1` if `estatus IN ('VENCIDO') AND dias_mora > 90`, else `0`.
Approximately 4% positive rate — realistic for a conservative lender.

**Why calibration matters here specifically:**
LightGBM outputs scores in [0,1] but they are not probabilities
unless the model is explicitly calibrated.
If the model outputs 0.6 for a loan but the actual default rate
among loans scored 0.5-0.7 is only 8%, then provisioning
based on that 0.6 score will overstate expected losses by 7x.

Use Platt scaling (logistic regression on the model outputs)
to align scores to actual probabilities.
Verify calibration with a reliability diagram:
if the model is calibrated, loans scored 0.1 should default
at approximately 10%, loans scored 0.3 at approximately 30%, etc.

**Writing scores back to Neo4J:**
```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://localhost:7687",
                               auth=("neo4j", "password"))

with driver.session() as session:
    for row in scored_df.collect():
        session.run("""
            MATCH (p:Prestamo {id_prestamo: $id})
            SET p.probabilidad_incumplimiento = $pd,
                p.score_version = $version,
                p.score_fecha = $fecha,
                p.model_name = $model
        """, id=row.id_prestamo,
             pd=float(row.pd_calibrada),
             version="v1.0.0",
             fecha=str(row.score_timestamp),
             model="lightgbm_creditgraph")
```

**This is the MLOps signal.**
The properties `score_version`, `score_fecha`, and `model_name`
on each Prestamo node mean that when you retrain in two months
and deploy v1.1.0, you can query: "which loans were scored
with v1.0.0 and have not been rescored?" You can compare
the distribution of PDs between versions to detect model drift.
You can audit any credit decision by looking at the score
that existed on the loan at the time the decision was made.
Without these properties, the graph stores a number with no context.
With them, it stores an auditable decision trail.

---

### Phase 4: Cypher Queries for Credit Risk (Day 2-3 — 4 hours)

These are the four queries that demonstrate you understand
what graphs are for in this domain.

**Query 1 — Direct exposure above threshold:**
```cypher
MATCH (c:ClienteIndividual)-[:TIENE_PRESTAMO]->(p:Prestamo)
WHERE p.estatus = 'ACTIVO'
  AND p.saldo_vigente_mxn > 100000
  AND p.probabilidad_incumplimiento > 0.15
RETURN c.nombre_completo,
       c.score_buro,
       p.id_prestamo,
       p.saldo_vigente_mxn,
       p.probabilidad_incumplimiento,
       p.saldo_vigente_mxn * p.probabilidad_incumplimiento AS expected_loss
ORDER BY expected_loss DESC
```

**Query 2 — Guarantee chain traversal (variable depth):**
```cypher
MATCH path = (garante:ClienteIndividual)
             -[:GARANTIZA*1..4]->(p:Prestamo)
             <-[:TIENE_PRESTAMO]-(deudor:ClienteIndividual)
WHERE deudor.id_cliente = 'CLI-00023'
  AND garante.id_cliente <> deudor.id_cliente
RETURN garante.nombre_completo,
       length(path) AS chain_depth,
       p.saldo_vigente_mxn,
       p.probabilidad_incumplimiento
ORDER BY chain_depth
```

**The `*1..4` syntax is what SQL cannot do without recursion.**
This single pattern traverses guarantee chains of any depth
from 1 to 4, returning every guarantor reachable from the
specified debtor within that range. The `length(path)` tells
you how many hops away each guarantor is.

**Query 3 — Circular guarantee detection:**
```cypher
MATCH path = (c:ClienteIndividual)
             -[:GARANTIZA*2..6]->(p:Prestamo)
             <-[:TIENE_PRESTAMO]-(c)
RETURN DISTINCT c.nombre_completo AS cliente_en_ciclo,
       length(path) AS ciclo_longitud,
       [n IN nodes(path) | coalesce(n.nombre_completo, n.id_prestamo)] AS ruta
```

**This query is impossible to express in standard SQL.**
It finds clients who are part of a guarantee cycle —
where following the guarantee chain eventually leads back
to the same client. The `DISTINCT` prevents returning
the same cycle multiple times from different starting points.

**Query 4 — Default contagion — total portfolio impact:**
```cypher
MATCH (deudor)-[:TIENE_PRESTAMO]->(p_defaulted:Prestamo)
WHERE p_defaulted.estatus = 'VENCIDO'
  AND p_defaulted.dias_mora > 90
WITH deudor, p_defaulted

MATCH (garante)-[:GARANTIZA {activa: true}]->(p_defaulted)
WITH garante,
     p_defaulted.saldo_vigente_mxn AS exposure,
     p_defaulted.id_prestamo AS loan_id

RETURN garante.nombre_completo AS guarantor,
       collect(loan_id) AS guaranteed_defaulted_loans,
       sum(exposure) AS total_indirect_exposure,
       count(*) AS num_defaulted_loans_guaranteed
ORDER BY total_indirect_exposure DESC
```

---

### Phase 5: Generative AI Query Layer (Day 3 — 3 hours)

**What you build:**
A Python module `05_graphrag.py` with one core function:

```python
def answer_portfolio_question(question: str, driver) -> str:
    """
    Takes a natural language question about the credit portfolio.
    Extracts relevant subgraph context using Cypher.
    Passes context to Claude API.
    Returns a grounded natural language answer.
    """
```

**The architecture decision:**
The LLM does not query Neo4J directly.
It receives structured text extracted by Cypher
and reasons over that text.

Why? Because LLMs hallucinate graph queries.
If you ask "which clients are exposed to Empresa X?"
and let the LLM generate the Cypher, it will often
generate syntactically valid but semantically wrong queries —
traversing relationships in the wrong direction,
missing the `activa: true` filter on guarantees,
or returning nodes from disconnected parts of the graph.

The correct architecture is:
1. Parse the question to determine query type
2. Run a predetermined Cypher query for that type
3. Format the results as structured text
4. Pass that text to the LLM with the question
5. Return the LLM's reasoning over real data

**The three question types the system handles:**

Type 1 — Exposure query:
"What is the total exposure of clients connected to Empresa MANUFACTURA_01?"
→ Runs Query 4 variant, formats results as a table in text, passes to LLM

Type 2 — Risk profile query:
"Which clients in CDMX have both high PD and active guarantees?"
→ Runs Query 1 variant filtered by state, adds guarantee context

Type 3 — Contagion scenario:
"If CLI-00023 defaults today, who else is affected and how much?"
→ Runs Query 2 to find all guarantors in chain,
  sums their indirect exposure, passes full chain to LLM

**The prompt structure:**
```python
context = f"""
Portfolio context extracted from the credit graph:

DIRECT LOANS AT RISK:
{format_loans_table(direct_loans)}

GUARANTEE CHAIN (depth up to 4):
{format_guarantee_chain(guarantee_chain)}

CORPORATE RELATIONSHIPS:
{format_corporate_relations(corporate_relations)}

Total direct exposure: MXN {total_direct:,.2f}
Total indirect exposure through guarantees: MXN {total_indirect:,.2f}
"""

prompt = f"""
You are a credit risk analyst reviewing a Mexican financial institution's portfolio.
You have been provided with factual data extracted from the credit risk graph.
Answer the following question using ONLY the data provided.
If the data does not contain enough information to answer, say so explicitly.
Do not infer or estimate values not present in the context.

Question: {question}

{context}
"""
```

**The "do not infer" instruction is not politeness.**
It is the critical constraint that makes the system auditable.
A risk analyst who presents a credit committee with AI-generated
exposure figures must be able to say those figures came from
the database, not from the model's training data.
The instruction enforces grounding.

---

## What Gets Committed to GitHub

```
creditgraph/
├── README.md               ← The document you show in the interview
├── data/
│   ├── generate_synthetic.py
│   └── schema_diagram.png  ← Draw.io or Excalidraw graph schema
├── notebooks/
│   ├── 01_etl_pyspark.ipynb      ← Databricks notebook
│   ├── 02_load_graph.py          ← Neo4J loading script
│   ├── 03_credit_scoring.ipynb   ← LightGBM + calibration
│   ├── 04_cypher_queries.md      ← All four queries with sample output
│   └── 05_graphrag.py            ← Generative AI layer
├── tests/
│   └── test_data_quality.py      ← Validates the embedded issues were caught
└── docs/
    └── architecture_decisions.md ← Why graph over SQL, why PySpark over pandas
```

**The `architecture_decisions.md` file is not optional.**
It is the document that demonstrates you made intentional choices,
not just followed a tutorial. It answers:
- Why Neo4J and not MongoDB or a relational DB with recursive CTEs?
- Why PySpark and not pandas?
- Why LightGBM and not logistic regression for credit scoring?
- Why calibrated probabilities and not raw model scores?
- Why predetermined Cypher in the AI layer and not LLM-generated queries?

One paragraph per decision. No word count minimum.
Precision over length.

---

## What This Project Is Not

It is not a production system. It does not handle authentication,
rate limiting, error recovery, or scale beyond one machine.

It is not a demonstration of Databricks administration.
You are using Databricks Community Edition as a PySpark runtime,
not as a managed platform.

It is not a complete MLOps implementation.
The version tagging on graph nodes is a pattern, not a system.
MLflow, model registry, drift detection — those come later.

It is a working prototype that demonstrates you understand
the problem space, made intentional architectural decisions,
and can build the core of what VinkOS is building for their client.

That is exactly what "useful on day one" means.

---

*Document version: 1.0 | Last updated: 2026-03-29*
*Context: VinkOS Data Scientist application preparation*
*Connected portfolio projects: Risk Analyst P03 (credit scoring),
Risk Analyst P10 (GNN contagion), Data Engineering Platform (PySpark ETL),
Regulation Agent (RAG architecture)*
