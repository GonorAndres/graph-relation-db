# Databricks notebook source

# MAGIC %md
# MAGIC # CreditGraph -- Credit Scoring with LightGBM + Platt Calibration
# MAGIC
# MAGIC This notebook trains a default prediction model on the clean CreditGraph portfolio
# MAGIC and writes calibrated probabilities of default (PD) back to Neo4J.
# MAGIC
# MAGIC **Why LightGBM.** Gradient boosting handles mixed feature types (continuous scores,
# MAGIC integer counts, categorical bands) without requiring scaling or one-hot encoding.
# MAGIC It is the de facto standard for tabular credit risk modeling.
# MAGIC
# MAGIC **Why calibration matters.** Raw model scores are ordinal rankings, not probabilities.
# MAGIC A LightGBM output of 0.6 does NOT mean "60% chance of default." It means "this loan
# MAGIC is riskier than one scored 0.4." The scores preserve rank order (discrimination) but
# MAGIC their absolute values are unreliable for provisioning math.
# MAGIC
# MAGIC Platt scaling (logistic regression fitted on raw model outputs) converts ordinal
# MAGIC scores into calibrated probabilities -- values where "0.04 means 4 out of 100 loans
# MAGIC like this actually default." This is the actuarial differentiator:
# MAGIC
# MAGIC - **Discrimination** (AUC): can the model rank-order risk? Most models do this well.
# MAGIC - **Calibration** (reliability diagram): do predicted probabilities match observed rates?
# MAGIC   Most models do this poorly without post-hoc correction.
# MAGIC
# MAGIC Both matter. AUC tells you the model can separate good from bad. Calibration tells
# MAGIC you the numbers are trustworthy for expected loss = PD x EAD x LGD.
# MAGIC
# MAGIC **Platform constraint.** This notebook runs on Databricks serverless compute, which
# MAGIC does not support Spark MLlib (VectorAssembler, GBTClassifier, etc. are blocked by
# MAGIC the Py4J security manager). On a classic cluster, the entire pipeline would stay
# MAGIC native Spark end-to-end. On serverless, we use PySpark for all data engineering
# MAGIC (joins, splits, feature selection) and cross to pandas only at the model training
# MAGIC boundary. At ~300 rows, `.toPandas()` is safe. Each pandas cell includes a comment
# MAGIC showing the Spark MLlib equivalent for reference.
# MAGIC
# MAGIC **Data context.** Reads clean Parquet produced by the PySpark ETL notebook.
# MAGIC Scores individual loans only (tipo_titular = INDIVIDUAL). Writes calibrated PDs
# MAGIC back to Neo4J Prestamo nodes with version metadata for audit trail.

# COMMAND ----------

# Install dependencies not included in standard Databricks runtime.
# LightGBM ships with Databricks ML Runtime; neo4j driver does not.
%pip install lightgbm neo4j --quiet

# COMMAND ----------

import os

# -- Paths --
CLEAN_PATH = "/Volumes/main/default/creditgraph/clean"
REFERENCE_DATE = "2026-03-15"

# -- Neo4J connection --
# In production, use Databricks secrets: dbutils.secrets.get(scope, key)
NEO4J_URI = os.environ.get("NEO4J_URI", "neo4j+s://1c09a89b.databases.neo4j.io")
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")  # Set via secrets or widget

# -- Model metadata --
SCORE_VERSION = "v1.0"
MODEL_NAME = "lightgbm_platt_v1"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Read Clean Parquet

# COMMAND ----------

from pyspark.sql import functions as F

clientes_df = spark.read.parquet(f"{CLEAN_PATH}/clientes/")
prestamos_df = spark.read.parquet(f"{CLEAN_PATH}/prestamos/")
empresas_df = spark.read.parquet(f"{CLEAN_PATH}/empresas/")

print(f"Clientes:  {clientes_df.count()} rows, {len(clientes_df.columns)} cols")
print(f"Prestamos: {prestamos_df.count()} rows, {len(prestamos_df.columns)} cols")
print(f"Empresas:  {empresas_df.count()} rows, {len(empresas_df.columns)} cols")

# Quick schema check
for col in ["id_cliente", "score_buro", "nivel_ingresos", "antiguedad_cliente_meses",
            "historico_incumplimientos"]:
    assert col in clientes_df.columns, f"Missing column: {col}"

for col in ["id_prestamo", "id_titular", "tipo_titular", "monto_original_mxn",
            "saldo_vigente_mxn", "tasa_interes_anual", "estatus", "dias_mora"]:
    assert col in prestamos_df.columns, f"Missing column: {col}"

print("\nSchema checks passed.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Feature Engineering
# MAGIC
# MAGIC All feature engineering stays in PySpark -- joins, filters, column selection,
# MAGIC null handling. No pandas needed for data preparation.

# COMMAND ----------

# Join clientes with their loans.
# Filter to INDIVIDUAL loans only -- we score person-level credit risk.
# Corporate loans (tipo_titular = "EMPRESA") require a different feature set
# (sector, anos_operacion, num_empleados) and a separate model.
individual_loans = prestamos_df.filter(F.col("tipo_titular") == "INDIVIDUAL")

feature_df = individual_loans.join(
    clientes_df,
    individual_loans["id_titular"] == clientes_df["id_cliente"],
    "inner"
)

# Feature columns from clientes
# - score_buro: bureau credit score (external signal)
# - nivel_ingresos: monthly income (capacity to repay)
# - antiguedad_cliente_meses: client tenure (stability signal)
# - historico_incumplimientos: past default count (behavioral signal)
#
# Feature columns from prestamos
# - monto_original_mxn: original disbursed amount
# - saldo_vigente_mxn: current outstanding balance -- THIS is the correct EAD
#   (Exposure at Default) proxy, not monto_original. A 1M loan with 100K
#   outstanding has 100K exposure, not 1M.
# - tasa_interes_anual: interest rate (risk pricing signal -- higher rate
#   often means the bank already assessed higher risk at origination)
# - dias_mora: days past due (strongest single predictor of near-term default)

feature_cols = [
    "score_buro",
    "nivel_ingresos",
    "antiguedad_cliente_meses",
    "historico_incumplimientos",
    "monto_original_mxn",
    "saldo_vigente_mxn",
    "tasa_interes_anual",
    "dias_mora",
]

keep_cols = ["id_prestamo", "id_titular", "estatus"] + feature_cols
feature_df = feature_df.select(*keep_cols)

# Drop rows with nulls in any feature column
before_count = feature_df.count()
feature_df = feature_df.dropna(subset=feature_cols)
after_count = feature_df.count()

print(f"Feature matrix: {after_count} rows x {len(feature_cols)} features")
print(f"Dropped {before_count - after_count} rows with null features")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Define Target Variable

# COMMAND ----------

# Default label: VENCIDO status (overdue loans).
# In production, the standard is VENCIDO + dias_mora > 90 days (Basel II definition).
# With synthetic data, we use VENCIDO status directly to preserve the ~4% positive
# rate calibrated in the data generation step.
feature_df = feature_df.withColumn(
    "default_label",
    F.when(F.col("estatus") == "VENCIDO", 1).otherwise(0)
)

# Class distribution
total = feature_df.count()
positives = feature_df.filter(F.col("default_label") == 1).count()
negatives = total - positives

print(f"Total loans:    {total}")
print(f"Defaults (1):   {positives}  ({positives / total * 100:.1f}%)")
print(f"Non-default (0): {negatives} ({negatives / total * 100:.1f}%)")
print(f"\nTarget positive rate: ~{positives / total * 100:.1f}%")
print("This matches the ~4% NPL calibration from the synthetic data generation.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Three-Way Split
# MAGIC
# MAGIC NOT two-way. Platt scaling needs a **held-out calibration set**.
# MAGIC
# MAGIC - If you calibrate on training data, the calibrator overfits to training scores.
# MAGIC - If you calibrate on test data, your test metrics are no longer unbiased.
# MAGIC - The calibration set is used ONLY for fitting the Platt scaler. It never
# MAGIC   touches training or final evaluation.

# COMMAND ----------

# 60% train / 20% calibration / 20% test -- split done in PySpark
train_df, cal_df, test_df = feature_df.randomSplit([0.6, 0.2, 0.2], seed=42)

train_count = train_df.count()
cal_count = cal_df.count()
test_count = test_df.count()

train_pos = train_df.filter(F.col("default_label") == 1).count()
cal_pos = cal_df.filter(F.col("default_label") == 1).count()
test_pos = test_df.filter(F.col("default_label") == 1).count()

print(f"Train:       {train_count} rows, {train_pos} positives ({train_pos/train_count*100:.1f}%)")
print(f"Calibration: {cal_count} rows, {cal_pos} positives ({cal_pos/cal_count*100:.1f}%)")
print(f"Test:        {test_count} rows, {test_pos} positives ({test_pos/test_count*100:.1f}%)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Convert to Pandas for Model Training
# MAGIC
# MAGIC **Why we cross to pandas here.** Databricks serverless compute does not support
# MAGIC Spark MLlib (VectorAssembler, GBTClassifier constructors are blocked by the Py4J
# MAGIC security manager). On a classic Databricks cluster, the Spark MLlib equivalent is:
# MAGIC
# MAGIC ```python
# MAGIC # --- Spark MLlib equivalent (requires classic cluster) ---
# MAGIC # from pyspark.ml.feature import VectorAssembler
# MAGIC # from pyspark.ml.classification import GBTClassifier
# MAGIC #
# MAGIC # assembler = VectorAssembler(inputCols=feature_cols, outputCol="features")
# MAGIC # assembled = assembler.transform(train_df)
# MAGIC #
# MAGIC # gbt = GBTClassifier(
# MAGIC #     featuresCol="features", labelCol="default_label",
# MAGIC #     maxDepth=4, maxIter=100, stepSize=0.05, seed=42
# MAGIC # )
# MAGIC # model = gbt.fit(assembled)
# MAGIC ```
# MAGIC
# MAGIC At ~300 rows, `.toPandas()` is safe (fits in driver memory).
# MAGIC The boundary where this breaks: ~100K+ rows on CE's single-node driver.
# MAGIC At that scale, you must use Spark MLlib or SynapseML's distributed LightGBM.

# COMMAND ----------

# .toPandas() boundary: PySpark for ETL, pandas for model training.
# Everything above this cell is distributed Spark. Everything below runs
# on the driver node in pandas/numpy.
train_pandas = train_df.toPandas()
cal_pandas = cal_df.toPandas()
test_pandas = test_df.toPandas()
feature_pandas = feature_df.toPandas()

target_col = "default_label"

X_train = train_pandas[feature_cols]
y_train = train_pandas[target_col]

X_cal = cal_pandas[feature_cols]
y_cal = cal_pandas[target_col]

X_test = test_pandas[feature_cols]
y_test = test_pandas[target_col]

print(f"X_train: {X_train.shape}, X_cal: {X_cal.shape}, X_test: {X_test.shape}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Train LightGBM
# MAGIC
# MAGIC **Serverless path:** LightGBM (Python, runs on driver).
# MAGIC
# MAGIC **Classic cluster equivalent:**
# MAGIC ```python
# MAGIC # gbt = GBTClassifier(featuresCol="features", labelCol="default_label",
# MAGIC #                     maxDepth=4, maxIter=100, stepSize=0.05, seed=42)
# MAGIC # model = gbt.fit(assembled_train_df)
# MAGIC # importances = model.featureImportances  # native Spark Vector
# MAGIC ```

# COMMAND ----------

import lightgbm as lgb

# Class imbalance: ~4% positive rate means a ~24:1 ratio.
# Without scale_pos_weight, the model learns to predict "no default" for
# everything and achieves 96% accuracy -- a degenerate classifier that
# is useless for risk management. scale_pos_weight tells the algorithm
# to penalize misclassifying a default 24x more than a non-default.
pos_rate = y_train.mean()
scale_weight = (1 - pos_rate) / pos_rate if pos_rate > 0 else 1.0

print(f"Training positive rate: {pos_rate:.4f}")
print(f"scale_pos_weight: {scale_weight:.1f}")

model = lgb.LGBMClassifier(
    n_estimators=200,
    max_depth=4,            # Shallow trees -- small dataset, avoid overfitting
    learning_rate=0.05,
    scale_pos_weight=scale_weight,
    min_child_samples=5,    # Small dataset needs lower minimum leaf size
    random_state=42,
    verbose=-1,
)
model.fit(X_train, y_train)

# Feature importances (split-based)
import pandas as pd
importance = pd.DataFrame({
    "feature": feature_cols,
    "importance": model.feature_importances_
}).sort_values("importance", ascending=False)

print("\nFeature importances (number of splits):")
print(importance.to_string(index=False))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Evaluate Raw Model (Before Calibration)
# MAGIC
# MAGIC **Serverless path:** sklearn metrics on pandas arrays.
# MAGIC
# MAGIC **Classic cluster equivalent:**
# MAGIC ```python
# MAGIC # from pyspark.ml.evaluation import BinaryClassificationEvaluator
# MAGIC # evaluator = BinaryClassificationEvaluator(
# MAGIC #     rawPredictionCol="rawPrediction", labelCol="default_label",
# MAGIC #     metricName="areaUnderROC"
# MAGIC # )
# MAGIC # auc = evaluator.evaluate(test_predictions)
# MAGIC #
# MAGIC # # Confusion matrix via PySpark groupBy:
# MAGIC # test_predictions.groupBy("default_label", "prediction").count().show()
# MAGIC ```

# COMMAND ----------

from sklearn.metrics import roc_auc_score, confusion_matrix, classification_report

# Raw predicted probabilities -- NOT calibrated yet.
y_test_proba_raw = model.predict_proba(X_test)[:, 1]
y_test_pred = model.predict(X_test)

auc_raw = roc_auc_score(y_test, y_test_proba_raw)
print(f"Test AUC (raw): {auc_raw:.4f}")
print(f"\nConfusion Matrix:")
print(confusion_matrix(y_test, y_test_pred))
print(f"\nClassification Report:")
print(classification_report(y_test, y_test_pred, zero_division="warn"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Platt Calibration
# MAGIC
# MAGIC Platt scaling fits a logistic regression on the **calibration set** raw scores.
# MAGIC This learns a sigmoid mapping from raw scores to calibrated probabilities.
# MAGIC
# MAGIC Key: we use the HELD-OUT calibration set, not training or test.
# MAGIC - Training set: calibrator would overfit to training scores
# MAGIC - Test set: test metrics would no longer be unbiased
# MAGIC - Calibration set: clean separation of concerns
# MAGIC
# MAGIC **Classic cluster equivalent:**
# MAGIC ```python
# MAGIC # from pyspark.ml.classification import LogisticRegression
# MAGIC # from pyspark.ml.feature import VectorAssembler
# MAGIC #
# MAGIC # score_assembler = VectorAssembler(inputCols=["raw_score"], outputCol="raw_score_vec")
# MAGIC # cal_for_platt = score_assembler.transform(cal_predictions)
# MAGIC #
# MAGIC # platt = LogisticRegression(featuresCol="raw_score_vec", labelCol="default_label",
# MAGIC #                            maxIter=100, regParam=0.0)
# MAGIC # calibrator = platt.fit(cal_for_platt)
# MAGIC ```

# COMMAND ----------

from sklearn.linear_model import LogisticRegression

# Get raw scores on the calibration set
y_cal_proba_raw = model.predict_proba(X_cal)[:, 1]

# Fit Platt scaler: logistic regression mapping raw_score -> P(default)
calibrator = LogisticRegression(solver="lbfgs")
calibrator.fit(y_cal_proba_raw.reshape(-1, 1), y_cal)

# Apply calibration to test set
y_test_proba_calibrated = calibrator.predict_proba(
    y_test_proba_raw.reshape(-1, 1)
)[:, 1]

print(f"Raw scores      -- mean: {y_test_proba_raw.mean():.4f}, std: {y_test_proba_raw.std():.4f}")
print(f"Calibrated PDs  -- mean: {y_test_proba_calibrated.mean():.4f}, std: {y_test_proba_calibrated.std():.4f}")
print(f"Actual def rate -- {y_test.mean():.4f}")
print()
print("After calibration, the mean predicted PD should be close to the actual")
print("default rate. This is what 'calibrated' means: the predictions are")
print("anchored to observed frequencies, not just rank-ordered.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 9. Reliability Diagram
# MAGIC
# MAGIC The reliability diagram (calibration curve) is the visual proof of calibration.
# MAGIC Points on the diagonal mean "when the model says 5%, 5% actually default."
# MAGIC Points above the diagonal mean underestimation. Points below mean overestimation.

# COMMAND ----------

# COMMAND ----------

# MAGIC %md
# MAGIC ## 10. Raw vs Calibrated Comparison

# COMMAND ----------

comparison = pd.DataFrame({
    "id_prestamo": test_pandas["id_prestamo"].values[:15],
    "actual_default": y_test.values[:15],
    "raw_score": y_test_proba_raw[:15],
    "calibrated_pd": y_test_proba_calibrated[:15],
})

print("Sample comparison -- raw score vs calibrated PD:")
print(comparison.to_string(index=False, float_format="%.4f"))
print()
print("Key insight: a raw score of 0.6 does NOT mean 60% default probability.")
print("The calibrated PD is what you use for expected loss = PD x EAD x LGD.")
print("Without calibration, provisions are systematically biased.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 11. Score All Individual Loans
# MAGIC
# MAGIC **Serverless path:** Score in pandas, then convert back to PySpark for write-back.
# MAGIC
# MAGIC **Classic cluster equivalent:**
# MAGIC ```python
# MAGIC # all_predictions = model.transform(assembled_all_df)
# MAGIC # all_calibrated = calibrator.transform(score_assembler.transform(all_predictions))
# MAGIC # scored_df = all_calibrated.select(
# MAGIC #     "id_prestamo",
# MAGIC #     vector_to_array("probability")[1].alias("probabilidad_incumplimiento"),
# MAGIC #     F.lit(SCORE_VERSION).alias("score_version"),
# MAGIC #     F.lit(REFERENCE_DATE).alias("score_fecha"),
# MAGIC #     F.lit(MODEL_NAME).alias("model_name"),
# MAGIC # )
# MAGIC ```

# COMMAND ----------

# Score all individual loans (not just test set)
X_all = feature_pandas[feature_cols]
y_all_raw = model.predict_proba(X_all)[:, 1]
y_all_calibrated = calibrator.predict_proba(y_all_raw.reshape(-1, 1))[:, 1]

scored_pandas = feature_pandas[["id_prestamo"]].copy()
scored_pandas["probabilidad_incumplimiento"] = y_all_calibrated
scored_pandas["score_version"] = SCORE_VERSION
scored_pandas["score_fecha"] = REFERENCE_DATE
scored_pandas["model_name"] = MODEL_NAME

# Convert back to PySpark DataFrame for consistency with the rest of the pipeline
scored_df = spark.createDataFrame(scored_pandas)

print(f"Scored {scored_df.count()} individual loans")
print("\nCalibrated PD distribution:")
scored_df.select(
    F.mean("probabilidad_incumplimiento").alias("mean"),
    F.stddev("probabilidad_incumplimiento").alias("std"),
    F.min("probabilidad_incumplimiento").alias("min"),
    F.expr("percentile_approx(probabilidad_incumplimiento, 0.5)").alias("median"),
    F.max("probabilidad_incumplimiento").alias("max"),
).show(truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 12. Write Calibrated PDs to Neo4J
# MAGIC
# MAGIC Write scores back to Prestamo nodes with version metadata so every score
# MAGIC is traceable to its model, date, and version. This is essential for
# MAGIC audit trail and model governance.
# MAGIC
# MAGIC We collect the scored DataFrame here because Neo4J write-back requires
# MAGIC a driver-side connection. With ~300 rows this is fine. At scale, you would
# MAGIC use the Neo4J Spark Connector (`org.neo4j.spark`) for distributed writes.

# COMMAND ----------

from neo4j import GraphDatabase


def write_scores_to_neo4j(scored_rows, uri, username, password):
    """Write calibrated PDs back to Neo4J Prestamo nodes.

    Uses UNWIND batch inserts for efficiency. Each Prestamo node gets:
    - probabilidad_incumplimiento: calibrated PD (float)
    - score_version: model version string
    - score_fecha: scoring reference date
    - model_name: model identifier for audit
    """
    driver = GraphDatabase.driver(uri, auth=(username, password))

    query = """
    UNWIND $records AS rec
    MATCH (p:Prestamo {id_prestamo: rec.id_prestamo})
    SET p.probabilidad_incumplimiento = rec.probabilidad_incumplimiento,
        p.score_version = rec.score_version,
        p.score_fecha = rec.score_fecha,
        p.model_name = rec.model_name
    """

    # Collect PySpark DataFrame to driver for Neo4J write
    records = [row.asDict() for row in scored_df.collect()]

    with driver.session() as session:
        batch_size = 100
        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            session.run(query, records=batch)
            print(f"  Written batch {i // batch_size + 1}: {len(batch)} records")

    driver.close()
    print(f"\nDone. {len(records)} calibrated PDs written to Neo4J.")


# Execute write-back
if NEO4J_PASSWORD:
    write_scores_to_neo4j(scored_df, NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD)
else:
    print("NEO4J_PASSWORD not set.")
    print("Set via Databricks secrets: dbutils.secrets.get('creditgraph', 'neo4j_password')")
    print("Or set the NEO4J_PASSWORD environment variable.")
    print("\nSkipping write-back. Scores are available in the scored_df DataFrame.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 13. Verify Scores in Neo4J

# COMMAND ----------

def verify_scores_in_neo4j(uri, username, password):
    """Sample scored loans from Neo4J to confirm write-back succeeded."""
    driver = GraphDatabase.driver(uri, auth=(username, password))

    sample_query = """
    MATCH (p:Prestamo)
    WHERE p.score_version IS NOT NULL
    RETURN p.id_prestamo AS id_prestamo,
           p.probabilidad_incumplimiento AS pd,
           p.score_version AS version,
           p.model_name AS model
    ORDER BY p.probabilidad_incumplimiento DESC
    LIMIT 10
    """

    with driver.session() as session:
        result = session.run(sample_query)
        records = [dict(r) for r in result]

    print("Scored loans in Neo4J (top 10 by PD):")
    for r in records:
        print(f"  {r['id_prestamo']}: PD={r['pd']:.4f}, version={r['version']}, model={r['model']}")

    with driver.session() as session:
        count = session.run(
            "MATCH (p:Prestamo) WHERE p.score_version IS NOT NULL RETURN count(p) AS n"
        ).single()["n"]

    driver.close()
    print(f"\nTotal scored loans in Neo4J: {count}")


if NEO4J_PASSWORD:
    verify_scores_in_neo4j(NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD)
else:
    print("Skipping verification -- NEO4J_PASSWORD not set.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## What This Means for Provisioning
# MAGIC
# MAGIC Calibrated PDs unlock continuous expected loss calculation:
# MAGIC
# MAGIC **EL = PD x EAD x LGD**
# MAGIC
# MAGIC - **PD** (Probability of Default): the calibrated score this notebook produces.
# MAGIC   A loan scored 0.08 means "8 out of 100 similar loans default."
# MAGIC - **EAD** (Exposure at Default): `saldo_vigente_mxn` -- the current outstanding
# MAGIC   balance, not the original disbursed amount.
# MAGIC - **LGD** (Loss Given Default): typically 45% for unsecured, 25% for secured
# MAGIC   (Basel II standard). Not modeled here but pluggable.
# MAGIC
# MAGIC **Without calibration,** provisions are based on CNBV regulatory buckets
# MAGIC (categorias A through E), which are coarse: a loan is either "normal" or
# MAGIC "watched" or "doubtful." There is no granularity between buckets.
# MAGIC
# MAGIC **With calibrated PDs,** you compute continuous expected loss per loan.
# MAGIC A loan with PD=0.03 and EAD=500K has EL=6,750 (at 45% LGD).
# MAGIC A loan with PD=0.12 and EAD=500K has EL=27,000. Same EAD, 4x the provision.
# MAGIC Regulatory buckets would put both in the same category.
# MAGIC
# MAGIC **The graph adds another dimension.** The stress test notebook showed that
# MAGIC defaults propagate through guarantee chains and corporate hubs. This means
# MAGIC portfolio expected loss > sum of individual expected losses, because defaults
# MAGIC are correlated through structural connections. The graph reveals HOW defaults
# MAGIC propagate. The model estimates HOW LIKELY each default is. Calibration ensures
# MAGIC those likelihoods are trustworthy enough to multiply by exposure.
# MAGIC
# MAGIC **Platform note.** On a classic Databricks cluster, every step from VectorAssembler
# MAGIC through GBTClassifier through Platt calibration runs natively in Spark MLlib --
# MAGIC no `.toPandas()`, no driver-side computation. Serverless compute restricts MLlib
# MAGIC access, so this notebook uses LightGBM via pandas at the model boundary. The
# MAGIC Spark MLlib equivalent is documented as comments in each cell for reference.
# MAGIC The ETL pipeline (upstream notebook) is 100% native PySpark regardless of
# MAGIC compute type.
# MAGIC
# MAGIC This is the full pipeline: **topology (graph) -> prediction (model) ->
# MAGIC calibration (Platt) -> provisioning (EL = PD x EAD x LGD).**
