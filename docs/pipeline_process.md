# CreditGraph Data Pipeline -- Process Documentation

**Purpose:** This document records every step of the data pipeline, what was
decided, why, and what the output means. Written for interview reference --
every section answers a question you'll be asked.

---

## Pipeline Overview

```
Script 00 --> Script 01 --> Script 02 --> Script 03 --> Script 04 --> Script 05 --> Script 06
 GLEIF API     UK PSC       Subgraph      Mexican        Embed         Embed         Neo4J
 (MX cos)    (UK persons)   extraction    identity +     5 scenarios   quality       LOAD CSV
                                          credit layer                 issues
```

Each script reads the previous script's output files. No shared state.
If script 03 fails, rerun from 03 -- scripts 00-02 don't need to rerun.

---

## Script 00: acquire_gleif.py

**What it does:** Fetches all active Mexican legal entities from the GLEIF API,
then scans for parent-child corporate relationships.

**Data source:** GLEIF (Global Legal Entity Identifier Foundation) API.
Open access, no authentication, no rate limits enforced.
- Endpoint: `https://api.gleif.org/api/v1/lei-records`
- Filter: `entity.legalAddress.country=MX`, `entity.status=ACTIVE`

**Why GLEIF:** Created after the 2008 financial crisis because regulators
couldn't trace Lehman Brothers' 7,000 entities across 40 countries. The G20
mandated a global entity identification system in 2011. GLEIF was established
in 2014 by the Financial Stability Board.

**How it works:**
1. Paginate through all active MX entities (page size 200, 36 pages)
2. For each entity, extract: LEI, legal name, jurisdiction, address (with
   ISO 3166-2 region codes like MX-CMX, MX-NLE), and `registeredAs` (often
   contains the entity's RFC -- Mexican tax ID)
3. Identify entities belonging to major financial groups by keyword matching
   (BBVA, Banorte, Santander, Bimbo, CEMEX, etc.)
4. For those ~445 priority entities, check parent-child relationships via
   the `direct-parent` and `direct-child-relationships` endpoints
5. Parent endpoints return 404 when no relationship exists (not empty response)
6. Deduplicate edges by (child_lei, parent_lei) pair

**Output:**
- `data/source/gleif_mx_entities.json` -- 7,015 active Mexican entities
- `data/source/gleif_relationships.json` -- 287 parent-child corporate edges

**Key findings:**
- Most MX entities are leaf nodes (no parent-child relationships)
- Large financial groups have rich hierarchies: BBVA Asset Management has 15
  investment fund subsidiaries; Grupo Bimbo has Barcel, Ricolino, and others
- 38 unique parent groups identified
- The `registeredAs` field contains real RFC codes for many entities
- Region codes (MX-CMX, MX-NLE, MX-JAL) provide real geographic distribution:
  CDMX 2,894; Estado de Mexico 800; Nuevo Leon 700; Jalisco 475

**Decisions made:**
- Used keyword matching to prioritize relationship scanning instead of checking
  all 7,015 entities (would require 7,015 API calls for parent checks)
- Accepted that non-financial-group entities are mostly leaf nodes
- Kept all 7,015 entities as a "name pool" for script 03 -- real Mexican
  company names are more convincing than Faker-generated ones

**Runtime:** ~9 minutes (36 pages + 445 parent checks at 0.3s delay)

---

## Script 01: acquire_psc.py

**What it does:** Queries the Open Ownership BODS Datasette for UK persons
who control multiple companies, then fetches their full company lists.

**Data source:** Open Ownership BODS (Beneficial Ownership Data Standard)
database, hosted as a public Datasette instance. Data snapshot: 2025-03-11.
CC0 license (public domain).
- Datasette URL: `https://bods-data-datasette.openownership.org/uk_version_0_4`
- Database: 38 GB SQLite, 16 tables, 12.2M person records, 5.8M entities

**Why UK PSC:** Since April 2016, UK law (Companies Act 2006, amended 2015)
requires every company to declare who controls it. A person must be declared
if they hold >25% of shares, >25% of voting rights, or have the right to
appoint/remove directors. This is the richest publicly available beneficial
ownership dataset in the world. Mexico has an equivalent concept ("personas
relacionadas" under CNBV Circular Unica de Bancos, Article 73) but the data
is not publicly available.

**Why Datasette instead of bulk download:**
- The full PSC snapshot is 2 GB (11M records). We need ~300 persons.
- Datasette allows SQL queries via HTTP -- no download, no registration.
- Tradeoff: Datasette has a 30-second query timeout and no custom indexes,
  so only name-based queries work. GROUP BY on 14M rows times out.

**How it works:**
1. Build a list of 112 common British full names (e.g., "Mr David Smith",
   "Mr Mohammed Ali", "Mrs Sarah Jones") -- these match the format stored
   in UK PSC data
2. Send names in batches of 40 to the Datasette SQL API:
   `SELECT fullname, birthdate, COUNT(DISTINCT company) ... GROUP BY ... HAVING >= 2`
3. For each controller found, fetch their full company list
4. Save persons, companies, and person-to-company edges

**Why name-based search (not arbitrary graph traversal):**
The Datasette has NO indexes on business columns (declarationsubject, recordid).
Only primary key auto-indexes exist. This means:
- `WHERE fullname IN (...)` works (scans the names table)
- `WHERE declarationsubject = 'GB-COH-12345'` times out (full scan on 14M rows)
- `GROUP BY recorddetails_interestedparty` times out (full scan)

We discovered this through testing. The name-based approach is a workaround
for the index limitation, not the ideal approach.

**Important data quirk:** Person IDs in BODS are per-company, not global.
The same real person (e.g., "Mr Ashok Patel", born 1970-09) has 7 different
`recorddetails_interestedparty` values -- one per company they control.
Identity matching requires name + birth month deduplication.

**Output:**
- `data/source/psc_persons.json` -- 600 multi-company controllers
- `data/source/psc_companies.json` -- 3,864 unique companies
- `data/source/psc_relationships.json` -- 3,935 person-to-company edges

**Key findings:**
- Top controller: Mr Christopher Jones (born 1975-12) controls 44 companies
- 600 persons found who each control 2+ companies
- Ownership bands available: 25-50%, 50-75%, 75-100% (not exact percentages)
- Control types: shareholding, voting rights, board appointment

**Runtime:** ~30 minutes (3 batch queries + 600 individual company lookups
at 1.5s delay each)

---

## Script 02: extract_subgraph.py

**What it does:** Builds a NetworkX bipartite graph from PSC data, finds
connected components, and selects ~300 persons + ~80 companies for the
CreditGraph.

**How it works:**
1. Load all source data (PSC + GLEIF)
2. Build a bipartite graph: Person nodes connected to Company nodes via
   CONTROLS edges
3. Find connected components using `nx.connected_components()`
4. Company-first selection strategy:
   a. First select companies with 2+ controllers (shared directors) -- 17 companies
   b. Expand to include all companies controlled by those persons -- 72 companies
   c. Fill remaining person slots, adding at most 1 company per new person
5. Include all 287 GLEIF corporate edges (these are a separate layer)

**Why company-first selection:**
First attempt used a component-based strategy: add whole connected components
until targets are reached. This produced 2,533 companies because most components
are star-shaped (1 person controlling many companies). The company-first
approach starts from the interesting core (shared directors) and expands outward,
keeping the company count controlled.

**What "connected component" means here:**
In graph theory, a connected component is a group of nodes where every node
can reach every other node through edges. In our bipartite graph:
- Two persons are in the same component if they SHARE a company
- Two companies are in the same component if the SAME person controls both

Most components are star-shaped: 1 person at the center, N companies as
spokes. These are NOT connected to each other -- Person A's 30 companies
have nothing to do with Person B's 24 companies unless A and B share a
company.

**The interesting topology:**
- 593 total components (very fragmented -- most persons don't share companies)
- 21 companies with 2+ controllers (shared directors)
- The Taylor pair: Mr Mark Taylor + Mr Richard Taylor co-control 7 companies
- Paul Smith + Andrew Smith co-control 2 companies; Andrew also shares one
  with Mark Jones -- creating a 3-person chain

**Output:**
- `data/source/subgraph_persons.json` -- 300 selected persons
- `data/source/subgraph_companies.json` -- 366 selected companies
- `data/source/subgraph_relationships.json` -- 674 edges (387 PSC + 287 GLEIF)
- `data/source/subgraph_stats.json` -- connectivity statistics

**Key stats:**
- 300 persons (target: 300)
- 366 companies (target: 80 -- will be trimmed in script 03 to ~80 Empresa nodes)
- 21 companies with shared directors (the topology core)
- 18 persons controlling multiple companies

---

## Script 03: map_to_creditgraph.py [PENDING]

**What it will do:** Three transformations:

**1. Identity mapping:**
- 300 UK persons --> 300 ClienteIndividual with Mexican identities
  - Name: Faker('es_MX') generates Mexican names
  - CURP: 18-character synthetic, structurally valid
  - Birth date: keep real month/year from PSC, synthesize day
  - State: map from UK region or assign from GLEIF state distribution
  - Income: lognormal(mean=25000, sigma=0.8) monthly MXN
  - Credit score: normal(650, 80) clipped to [300, 850]
  - Default history: Poisson(0.3) clipped to [0, 5]

- ~80 companies from the 366 --> 80 Empresa with Mexican attributes
  - Name: use real GLEIF MX company names where possible
  - RFC: 12-character synthetic, valid format
  - Sector: mapped from UK SIC codes or assigned
  - Revenue: lognormal, sector-dependent
  - Size: derived from employee count thresholds (MICRO/PEQUENA/MEDIANA/GRANDE)

**2. Loan generation:**
- 450 Prestamo records, 70% individual / 30% corporate
- Amounts: lognormal(12.0, 0.8) for individuals (~MXN 160K median),
  lognormal(14.0, 1.0) for corporate (~MXN 1.2M median)
- Status: 72% ACTIVO, 15% PAGADO, 8% VENCIDO, 5% REESTRUCTURADO
- Default correlation: entities in connected subgraph components get
  slightly higher default probability

**3. Guarantee generation:**
- 180 guarantee edges following ownership topology:
  - Shareholder of Company X guarantees X's loan (p=0.4)
  - Co-shareholders cross-guarantee personal loans (p=0.15)
  - Parent company guarantees subsidiary's loan (p=0.3)
  - 20-30 random guarantees for non-connected entities

**Output:** 5 raw CSV files in `data/raw/`

---

## Script 04: embed_scenarios.py [PENDING]

**What it will do:** Plant the 5 structural scenarios that make the Cypher
queries non-trivial. Each scenario is designed to demonstrate a specific
graph capability that SQL cannot match.

1. **Guarantee chain depth 3:** A-->B-->C, C is VENCIDO (45 dias mora).
   Demonstrates variable-length path traversal `[:GARANTIZA*1..4]`.

2. **Circular guarantee:** X-->Y-->Z-->X, all ACTIVO.
   Illegal under CNBV Circular 3/2012 (fictitious coverage).
   Demonstrates cycle detection -- impossible in standard SQL.

3. **Corporate contagion hub:** 1 company (REESTRUCTURADO) with 5 shareholders,
   2 of whom cross-guarantee personal loans.
   Demonstrates multi-hop contagion traversal.

4. **Shared director:** 1 person directs 2 companies, both with active loans.
   "Partes relacionadas" concentration risk flag.
   Uses real shared-director topology from PSC data.

5. **Unsecured high-PD loans:** 15 loans with no guarantor, PD > 0.25, ACTIVO.
   Demonstrates relationship absence query + property filter.

---

## Script 05: embed_quality_issues.py [PENDING]

**What it will do:** Inject the exact data quality problems documented in the
spec. These are real problems that bank data teams encounter:

- Negative incomes (inverts the risk signal in ML)
- Duplicate clients (same CURP, different ID -- double-counts concentration)
- Orphaned FK references (loan points to nonexistent client)
- Invalid CURP format (wrong length)
- Future birth dates, minors (regulatory violation)
- saldo_vigente > monto_original (logical impossibility)
- dias_mora > 0 on ACTIVO loans (status inconsistency)
- Guarantee coverage > 100% (process failure)

Every rejected record gets a `rejection_reason` column. Silent drops are
not acceptable -- the audit trail matters.

---

## Script 06: generate_neo4j_load.py [PENDING]

**What it will do:** Generate:
- Clean CSVs (post-validation, for Neo4J ingestion) in `data/clean/`
- `neo4j/load_all.cypher` -- LOAD CSV Cypher commands
- Creates node uniqueness constraints first, then loads nodes, then relationships

---

## Script 04b: add_gleif_hierarchy.py

**What it does:** Adds real Mexican corporate groups (BBVA, Grupo Bimbo,
Banco Inbursa) as parent-child Empresa nodes with ES_SUBSIDIARIA_DE edges.

**Why this was a separate step:** Scripts 00-02 acquired both UK PSC and
GLEIF MX data, but script 03 only mapped the PSC topology into the graph.
The 287 GLEIF parent-child edges were left unused because the two datasets
have ZERO entity overlap -- UK company numbers (GB-COH-XXXXXXXX) and
Mexican LEI codes (20-char alphanumeric) share no common identifier.

The original plan assumed a bridge would exist (MX subsidiary → UK parent →
PSC persons), but Mexican GLEIF entities mostly connect to Spanish or US
parents, not UK ones.

This script adds the GLEIF corporate hierarchies as a **separate topology
layer** demonstrating company→company contagion (if the parent fails, all
subsidiaries are exposed).

**What was added:**
- BBVA Asset Management Mexico (parent) + 5 investment fund subsidiaries
- Grupo Bimbo SAB de CV (parent) + 4 subsidiaries (Ricolino, Barcel, etc.)
- Banco Inbursa / Grupo Financiero Inbursa (parent) + 3 SIEFORE subsidiaries
- Each entity received a loan so it has credit exposure in the graph

**Topology limitations (honest):**
The GLEIF parent-child layer is a flat tree: one parent, N children,
100% ownership assumed, one level deep. Real corporate groups have
complexity this data does NOT capture:
- Cross-holdings (A owns part of B, B owns part of A)
- Multi-level nesting (parent → subsidiary → sub-subsidiary → fund)
- Joint ventures (two parents co-owning one child)
- Circular ownership within grupos financieros
- Minority stakes across unrelated groups

The PSC person→company layer has richer topology (real shared directors,
real ownership bands) but also misses family relationships between
controllers, indirect control through trusts, and temporal changes.

**The honest framing:** Real data would have MORE connections than our
synthetic construction, making the graph approach MORE valuable, not less.
Our simple tree demonstrates the METHOD. Production data would make the
findings deeper.

**Output:** Modified empresas_raw.csv (80 → 95), relaciones_raw.csv
(87 → 99), prestamos_raw.csv (451 → 466)

---

## How the Two Data Layers Relate

```
LAYER 1 (UK PSC topology):              LAYER 2 (GLEIF MX hierarchy):
Person ──[ES_ACCIONISTA_DE]──> Company   Company ──[ES_SUBSIDIARIA_DE]──> Parent
Person ──[ES_DIRECTOR_DE]──> Company     (flat tree, 1 level deep)
  84 edges, shared directors             12 edges, 3 corporate groups
  Scenarios 1-5 live here                Corporate contagion lives here

         NO CONNECTION BETWEEN LAYERS
         (different ID systems, no bridge entity)
```

This separation is an artifact of available public data, not a design choice.
In production at VinkOS, the institution's internal data would connect both
layers -- the same person who is a director of Company A (Layer 1) might also
sit on the board of BBVA subsidiary B (Layer 2). That unified graph is what
makes the real system valuable. Our prototype demonstrates each pattern
independently.

---

## Data Provenance Summary

| Data | Source | License | Date | Real/Synthetic |
|------|--------|---------|------|----------------|
| MX company entities | GLEIF API | Open access | 2026-03-29 (live) | Real |
| MX corporate hierarchies | GLEIF API Level 2 | Open access | 2026-03-29 (live) | Real |
| UK person-company control | Open Ownership BODS | CC0 | 2025-03-11 (snapshot) | Real |
| Person identities (Mexican) | Faker es_MX + CURP generator | N/A | Generated | Synthetic |
| Company attributes (Mexican) | GLEIF names + synthetic fields | Mixed | Mixed | Hybrid |
| Loans, guarantees, defaults | numpy distributions | N/A | Generated | Synthetic |
| Data quality issues | Catalogued from real bank operations | N/A | Embedded | Realistic |

---

## Key Technical Decisions Log

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| GLEIF API over bulk download | 2GB Golden Copy file | API is paginated, targeted, no file management |
| BODS Datasette over PSC snapshot | 2GB PSC ZIP + stream parse | No download needed, user prioritized getting to graph fast |
| Name-based PSC search | Full table GROUP BY, bulk download | Datasette has no indexes; name search is the only query pattern that works within 30s timeout |
| Company-first subgraph selection | Component-based selection | Component-based produced 2,533 companies (star-shaped components); company-first stays near target |
| Keep UK topology, replace labels | Fully synthetic topology | Real ownership has non-trivial structures (shared directors, cross-holdings) that random generators can't replicate |
| ~80 companies, not all 366 | Use all selected companies | Spec targets 80 Empresa nodes; trimming in script 03 keeps the graph focused |

---

---

## Script 05: embed_quality_issues.py

**What it does:** Injects 127 data quality issues across all 5 entity files.
Each issue is annotated inline with why it happens in real banking and what
breaks if it's not caught.

See the script source for inline documentation of every issue category.

**Output:** Modified `data/raw/*.csv` files + `data/source/quality_issues_manifest.json`

---

## Script 06: generate_neo4j_load.py

**What it does:** Minimal validation (orphaned FKs only) + clean CSV generation
+ Cypher LOAD CSV script generation.

**Only removes records that would crash Neo4J LOAD:**
- Loans referencing nonexistent borrowers (8 removed)
- Guarantees referencing nonexistent loans or guarantors (12 removed)
- Relations referencing nonexistent persons or companies (6 removed)
- Total: 26 records rejected with documented reasons

**Everything else stays dirty** for the PySpark ETL session (Phase 2).

**Output:**
- `data/clean/*.csv` -- minimally validated CSVs for Neo4J
- `data/clean/rejected_records.csv` -- audit trail with rejection reasons
- `neo4j/constraints.cypher` -- uniqueness constraints (run first)
- `neo4j/load_all.cypher` -- full LOAD CSV Cypher script

*Last updated: 2026-03-31 | All scripts complete (00-06)*
