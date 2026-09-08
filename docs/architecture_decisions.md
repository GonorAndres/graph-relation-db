# Architecture decisions

## Start with the review decision

The visitor is assessing analytical judgment. Selecting a pattern exposes its loans, distinct-loan exposure, interpretation, and suggested review. Technical details follow the business consequence.

Connected exposure is not loss. Guarantees attach to specific loans; chains do not create automatic liability. Ownership signals common dependency without determining default or loss severity. Circular support is a review flag, not proof of invalidity or zero recovery.

## Static evidence, one data source

The site consumes versioned demo and model JSON. The demo is a small fictional fixture; experimental predictions describe a different population. Loan records drive both the table and totals. No credentials or externally hosted graph are needed. D3 is bundled with its license.

Artifacts load independently so model failure does not hide the investigation. Errors are visible and retryable. Standard controls and a loan table provide alternatives to graph interaction.

## Relationship modeling without SQL overclaims

Loan nodes participate in ownership and guarantee relationships. Graph representation makes these paths inspectable; recursive SQL can also traverse relationships and detect cycles. No benchmark or SQL-exclusivity claim is made.

Browser types are person/company/loan and owns/guarantees/controls/shareholder. Query excerpts illustrate a mapping to capitalized Neo4j labels and uppercase edges. They do not query the historical database or claim unchanged compatibility.

## Forecasting with a negative control

Observation-date attributes precede simulated outcomes. Hidden probabilities and group shocks remain outside the predictor allowlist. Whole connected groups stay within one partition. Preprocessing uses training data; calibration uses calibration data.

The experiment varies network strength with common seeds, predictor data, and partitions. Absent network effects is a negative control. Logistic regression and constant-rate references test whether model complexity helps; matched LightGBM models isolate additional graph features.

Financial attributes are standardized synthetic quantities, not empirical accounting ratios. Connected stress is aligned with the outcome generator by design. Results test that mechanism, not banking validity. Group-bootstrap intervals condition on fitted runs; they do not establish temporal generalization or causation.

## Historical work

Earlier acquisition scripts and cloud notebooks remain research artifacts, not the runtime. Historical outputs are intact. Their superseded claims are identified in the README. No implemented GraphRAG layer or production-readiness claim is implied.
