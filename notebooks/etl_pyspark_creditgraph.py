# Databricks notebook source
# MAGIC %md
# MAGIC # CreditGraph ETL -- PySpark Data Validation Pipeline
# MAGIC 500-client Mexican credit portfolio knowledge graph. 5 raw CSVs with 127 embedded quality issues
# MAGIC (duplicate CURPs, orphaned FKs, negative incomes, state code inconsistencies, etc.).
# MAGIC This notebook validates, corrects where appropriate, rejects where not, and writes clean Parquet.
# MAGIC Synthetic credit layer on real ownership topology (UK PSC + GLEIF MX).

# COMMAND ----------

# Configuration constants
REFERENCE_DATE = "2026-03-15"  # Frozen for deterministic age/expiry calculations
RAW_PATH = "/Volumes/main/default/creditgraph"
CLEAN_PATH = "/Volumes/main/default/creditgraph/clean"
REJECTED_PATH = "/Volumes/main/default/creditgraph/rejected"

MIN_AGE_YEARS = 18
MAX_SCORE_BURO = 850
MIN_SCORE_BURO = 300
MAX_TASA_INTERES = 0.80  # CNBV usury ceiling approximation

# State standardization mappings
CLIENTE_STATE_MAP = {"Ciudad de Mexico": "CDMX"}
EMPRESA_STATE_MAP = {
    "CMX": "CDMX",
    "NL": "Nuevo Leon",
    "JAL": "Jalisco",
    "MEX": "Estado de Mexico",
    "QRO": "Queretaro",
}

# COMMAND ----------

# MAGIC %md
# MAGIC ## DBFS Upload Instructions
# MAGIC Upload the 5 raw CSVs via Databricks CLI before running this notebook:
# MAGIC ```
# MAGIC databricks fs cp data/raw/clientes_raw.csv dbfs:/FileStore/tables/creditgraph/raw/
# MAGIC databricks fs cp data/raw/empresas_raw.csv dbfs:/FileStore/tables/creditgraph/raw/
# MAGIC databricks fs cp data/raw/prestamos_raw.csv dbfs:/FileStore/tables/creditgraph/raw/
# MAGIC databricks fs cp data/raw/garantias_raw.csv dbfs:/FileStore/tables/creditgraph/raw/
# MAGIC databricks fs cp data/raw/relaciones_raw.csv dbfs:/FileStore/tables/creditgraph/raw/
# MAGIC ```
# MAGIC Or use the Databricks web UI: Workspace > Import > Upload to DBFS.

# COMMAND ----------

# Verify DBFS files exist before proceeding
try:
    files = dbutils.fs.ls(RAW_PATH)
    print(f"Found {len(files)} files in {RAW_PATH}:\n")
    expected = {
        "clientes_raw.csv", "empresas_raw.csv", "prestamos_raw.csv",
        "garantias_raw.csv", "relaciones_raw.csv",
    }
    found = set()
    for f in files:
        name = f.name.rstrip("/")
        size_kb = f.size / 1024
        print(f"  {name:30s} {size_kb:8.1f} KB")
        found.add(name)
    missing = expected - found
    if missing:
        print(f"\nMISSING: {missing}")
    else:
        print("\nAll 5 expected files present.")
except Exception as e:
    print(f"ERROR: Cannot list {RAW_PATH} -- {e}")
    print("Upload CSVs first (see cell above).")

# COMMAND ----------

# Explicit schemas -- all dates as StringType to prevent silent nulls from bad formats.
# Numeric columns that may contain nulls typed as DoubleType/IntegerType (Spark handles
# null promotion automatically for these types).
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, IntegerType,
)

schema_clientes = StructType([
    StructField("id_cliente", StringType(), False),
    StructField("nombre_completo", StringType(), True),
    StructField("curp", StringType(), True),
    StructField("fecha_nacimiento", StringType(), True),
    StructField("estado_residencia", StringType(), True),
    StructField("nivel_ingresos", DoubleType(), True),
    StructField("antiguedad_cliente_meses", IntegerType(), True),
    StructField("score_buro", DoubleType(), True),
    StructField("historico_incumplimientos", IntegerType(), True),
    StructField("fecha_ultimo_incumplimiento", StringType(), True),
])

schema_empresas = StructType([
    StructField("id_empresa", StringType(), False),
    StructField("razon_social", StringType(), True),
    StructField("rfc", StringType(), True),
    StructField("sector", StringType(), True),
    StructField("tamano", StringType(), True),
    StructField("ingresos_anuales_mxn", DoubleType(), True),
    StructField("anos_operacion", IntegerType(), True),
    StructField("num_empleados", IntegerType(), True),
    StructField("estado_registro", StringType(), True),
])

schema_prestamos = StructType([
    StructField("id_prestamo", StringType(), False),
    StructField("id_titular", StringType(), True),
    StructField("tipo_titular", StringType(), True),
    StructField("monto_original_mxn", DoubleType(), True),
    StructField("saldo_vigente_mxn", DoubleType(), True),
    StructField("tasa_interes_anual", DoubleType(), True),
    StructField("fecha_inicio", StringType(), True),
    StructField("fecha_vencimiento", StringType(), True),
    StructField("estatus", StringType(), True),
    StructField("dias_mora", IntegerType(), True),
    StructField("probabilidad_incumplimiento", DoubleType(), True),
    StructField("score_version", StringType(), True),
    StructField("score_fecha", StringType(), True),
])

schema_garantias = StructType([
    StructField("id_garantia", StringType(), False),
    StructField("id_prestamo", StringType(), True),
    StructField("id_garante", StringType(), True),
    StructField("tipo_garantia", StringType(), True),
    StructField("cobertura_porcentaje", DoubleType(), True),
    StructField("fecha_inicio", StringType(), True),
    StructField("fecha_vencimiento", StringType(), True),
    StructField("activa", StringType(), True),  # StringType -- "True"/"False", not boolean
])

schema_relaciones = StructType([
    StructField("id_relacion", StringType(), False),
    StructField("id_individuo", StringType(), True),
    StructField("id_empresa", StringType(), True),
    StructField("tipo_relacion", StringType(), True),
    StructField("porcentaje_participacion", DoubleType(), True),
    StructField("fecha_inicio", StringType(), True),
    StructField("fecha_fin", StringType(), True),
    StructField("activa", StringType(), True),
])

# COMMAND ----------

# Read all 5 CSVs with explicit schemas -- no inferSchema, no surprises
clientes_raw = (
    spark.read.option("header", "true")
    .schema(schema_clientes)
    .csv(f"{RAW_PATH}/clientes_raw.csv")
)
empresas_raw = (
    spark.read.option("header", "true")
    .schema(schema_empresas)
    .csv(f"{RAW_PATH}/empresas_raw.csv")
)
prestamos_raw = (
    spark.read.option("header", "true")
    .schema(schema_prestamos)
    .csv(f"{RAW_PATH}/prestamos_raw.csv")
)
garantias_raw = (
    spark.read.option("header", "true")
    .schema(schema_garantias)
    .csv(f"{RAW_PATH}/garantias_raw.csv")
)
relaciones_raw = (
    spark.read.option("header", "true")
    .schema(schema_relaciones)
    .csv(f"{RAW_PATH}/relaciones_raw.csv")
)

print("Row counts:")
print(f"  clientes:   {clientes_raw.count()}")
print(f"  empresas:   {empresas_raw.count()}")
print(f"  prestamos:  {prestamos_raw.count()}")
print(f"  garantias:  {garantias_raw.count()}")
print(f"  relaciones: {relaciones_raw.count()}")
print()
clientes_raw.printSchema()

# COMMAND ----------

# --- Lazy evaluation demo ---
# Chain several transforms WITHOUT triggering execution. Spark builds a DAG of
# transformations; Catalyst optimizes it; nothing moves until an ACTION fires.
from pyspark.sql import functions as F

lazy_demo = (
    clientes_raw
    .filter(F.col("nivel_ingresos").isNotNull())            # transformation 1
    .withColumn("ingreso_mensual", F.col("nivel_ingresos") / 12)  # transformation 2
    .filter(F.col("score_buro") >= 600)                      # transformation 3
    .select("id_cliente", "nombre_completo", "ingreso_mensual", "score_buro")  # transformation 4
)

# No data has moved yet. The explain() below shows the logical and physical plan
# that Catalyst built from the DAG. Only an action (count, show, write) triggers
# actual data processing.
lazy_demo.explain(mode="extended")

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.window import Window


def validate_and_split(df, conditions_dict, id_col, entity_name):
    """
    Apply validation rules and split into clean / rejected.

    Parameters
    ----------
    df : DataFrame
        Input DataFrame to validate.
    conditions_dict : dict[str, Column]
        {"rule_name": boolean_column} -- True means the record FAILS that rule.
    id_col : str
        Primary key column name (for logging).
    entity_name : str
        Human label for print output.

    Returns
    -------
    (clean_df, rejected_df)
        rejected_df includes a `rejection_reasons` column (pipe-delimited).
    """
    # Build a single column that concatenates all triggered rule names
    reason_parts = [
        F.when(cond, F.lit(name)) for name, cond in conditions_dict.items()
    ]
    df_flagged = df.withColumn(
        "rejection_reasons",
        F.concat_ws(" | ", *reason_parts),
    )

    rejected = df_flagged.filter(F.col("rejection_reasons") != "")
    clean = df_flagged.filter(F.col("rejection_reasons") == "").drop("rejection_reasons")

    rej_count = rejected.count()
    clean_count = clean.count()
    print(f"[{entity_name}]  raw={clean_count + rej_count}  clean={clean_count}  rejected={rej_count}")

    return clean, rejected

# COMMAND ----------

def standardize_state(col_name, mapping):
    """
    Build a chained F.when expression from a mapping dict.
    Non-matching values pass through unchanged.
    """
    expr = F.col(col_name)
    for old_val, new_val in mapping.items():
        expr = F.when(F.col(col_name) == old_val, F.lit(new_val)).otherwise(expr)
    return expr


# Apply state standardization -- these are CORRECTIONS, not rejections.
# The raw data has inconsistent codes (e.g. "CMX" vs "CDMX") that we normalize.
clientes_std = clientes_raw.withColumn(
    "estado_residencia", standardize_state("estado_residencia", CLIENTE_STATE_MAP)
)
empresas_std = empresas_raw.withColumn(
    "estado_registro", standardize_state("estado_registro", EMPRESA_STATE_MAP)
)

# Quick check: show corrected state values
print("Clientes -- distinct estado_residencia after standardization:")
clientes_std.select("estado_residencia").distinct().sort("estado_residencia").show(truncate=False)
print("Empresas -- distinct estado_registro after standardization:")
empresas_std.select("estado_registro").distinct().sort("estado_registro").show(truncate=False)

# COMMAND ----------

# --- Validate clientes (56 embedded issues) ---
# Rejection rules: structurally invalid records that cannot be trusted.
# null_income and null_state are NOT rejection criteria -- records can proceed with nulls.

clientes_conditions = {
    "null_name": (
        F.col("nombre_completo").isNull() | (F.trim(F.col("nombre_completo")) == "")
    ),
    "placeholder_name": (
        F.col("nombre_completo").rlike("(?i)(test|prueba|xxx|pendiente)")
    ),
    "invalid_curp_length": (
        F.col("curp").isNotNull() & (F.length("curp") != 18)
    ),
    "duplicate_curp": (
        # Window-based: flag ALL rows sharing a duplicated CURP (not just the second)
        (F.col("curp").isNotNull())
        & (F.count("id_cliente").over(Window.partitionBy("curp")) > 1)
    ),
    "future_birthdate": (
        F.col("fecha_nacimiento").isNotNull()
        & (F.to_date(F.col("fecha_nacimiento")) > F.to_date(F.lit(REFERENCE_DATE)))
    ),
    "minor": (
        F.col("fecha_nacimiento").isNotNull()
        & (
            F.months_between(
                F.to_date(F.lit(REFERENCE_DATE)),
                F.to_date(F.col("fecha_nacimiento")),
            )
            < (MIN_AGE_YEARS * 12)
        )
    ),
    "negative_income": (
        F.col("nivel_ingresos").isNotNull() & (F.col("nivel_ingresos") < 0)
    ),
    "score_out_of_range": (
        F.col("score_buro").isNotNull()
        & (
            (F.col("score_buro") < MIN_SCORE_BURO)
            | (F.col("score_buro") > MAX_SCORE_BURO)
        )
    ),
}

clientes_clean, clientes_rejected = validate_and_split(
    clientes_std, clientes_conditions, "id_cliente", "clientes"
)

# Show a sample of rejected records
print("\nSample rejected clientes:")
clientes_rejected.select("id_cliente", "nombre_completo", "curp", "rejection_reasons").show(
    10, truncate=False
)

# COMMAND ----------

# --- Validate empresas (18 embedded issues) ---
# Only truly broken records get rejected (null_name -- can't identify the entity).
# RFC length, null revenue, zero revenue, null employees are quality FLAGS but the
# record is still usable for FK joins and graph structure.

empresas_conditions = {
    "null_name": (
        F.col("razon_social").isNull() | (F.trim(F.col("razon_social")) == "")
    ),
}

empresas_clean, empresas_rejected = validate_and_split(
    empresas_std, empresas_conditions, "id_empresa", "empresas"
)

# Quality flags (not rejections) -- surface these for awareness
print("\nQuality flags (empresas, NOT rejected):")
flag_individual_rfc = empresas_clean.filter(
    F.col("rfc").isNotNull() & (F.length("rfc") != 12)
).count()
flag_null_revenue = empresas_clean.filter(F.col("ingresos_anuales_mxn").isNull()).count()
flag_zero_revenue = empresas_clean.filter(F.col("ingresos_anuales_mxn") == 0).count()
flag_null_employees = empresas_clean.filter(F.col("num_empleados").isNull()).count()
print(f"  individual_rfc_format (len!=12): {flag_individual_rfc}")
print(f"  null_revenue:                    {flag_null_revenue}")
print(f"  zero_revenue:                    {flag_zero_revenue}")
print(f"  null_employees:                  {flag_null_employees}")

# COMMAND ----------

# Cache clientes and empresas -- they're needed for FK validation in prestamos,
# garantias, and relaciones. Force materialization with .count() so the cache
# is populated before downstream joins.
clientes_clean.cache()
empresas_clean.cache()

cli_count = clientes_clean.count()
emp_count = empresas_clean.count()
print(f"Cached: {cli_count} clientes, {emp_count} empresas")

# COMMAND ----------

# --- Validate prestamos (29 embedded issues) ---
# FK validation via anti-join -- NOT .isin(collected_list).
# Why: .isin() collects all IDs to the driver and broadcasts them. With 300 clients
# that's fine, but the PATTERN doesn't scale. Anti-join stays distributed and lets
# Spark optimize the join strategy (broadcast hash join for small tables, sort-merge
# for large ones). We use the scalable pattern even at small scale.

# Build universe of valid titular IDs (clients + empresas)
valid_cli_ids = clientes_clean.select(F.col("id_cliente").alias("id_titular"))
valid_emp_ids = empresas_clean.select(F.col("id_empresa").alias("id_titular"))
valid_titular_ids = valid_cli_ids.unionByName(valid_emp_ids)

# Left join + null check to flag orphaned FKs (distributed, no driver collection)
prestamos_flagged = prestamos_raw.join(
    valid_titular_ids.withColumn("_valid", F.lit(True)),
    on="id_titular",
    how="left",
).withColumn(
    "orphaned_fk",
    F.col("_valid").isNull(),
).drop("_valid")

prestamos_conditions = {
    "orphaned_fk": F.col("orphaned_fk"),
    "type_mismatch": (
        (
            (F.col("tipo_titular") == "EMPRESA")
            & F.col("id_titular").startswith("CLI-")
        )
        | (
            (F.col("tipo_titular") == "INDIVIDUO")
            & F.col("id_titular").startswith("EMP-")
        )
    ),
    "null_amount": F.col("monto_original_mxn").isNull(),
    "negative_amount": (
        F.col("monto_original_mxn").isNotNull() & (F.col("monto_original_mxn") < 0)
    ),
    "saldo_exceeds_monto": (
        F.col("saldo_vigente_mxn").isNotNull()
        & F.col("monto_original_mxn").isNotNull()
        & (F.col("saldo_vigente_mxn") > F.col("monto_original_mxn"))
    ),
    "usury_rate": (
        F.col("tasa_interes_anual").isNotNull()
        & (F.col("tasa_interes_anual") > MAX_TASA_INTERES)
    ),
    "start_after_end": (
        F.col("fecha_inicio").isNotNull()
        & F.col("fecha_vencimiento").isNotNull()
        & (F.to_date(F.col("fecha_inicio")) > F.to_date(F.col("fecha_vencimiento")))
    ),
    "mora_on_activo": (
        (F.col("dias_mora").isNotNull())
        & (F.col("dias_mora") > 0)
        & (F.col("estatus") == "ACTIVO")
    ),
}

prestamos_clean, prestamos_rejected = validate_and_split(
    prestamos_flagged, prestamos_conditions, "id_prestamo", "prestamos"
)
# Drop helper column from clean output
prestamos_clean = prestamos_clean.drop("orphaned_fk")

print("\nSample rejected prestamos:")
prestamos_rejected.select("id_prestamo", "id_titular", "tipo_titular", "rejection_reasons").show(
    10, truncate=False
)

# COMMAND ----------

# --- Validate garantias (18 embedded issues) ---
# FK validation against CLEAN prestamos and CLEAN clientes+empresas.
# Orphaned FKs are rejected. Status/date mismatches are quality flags.

valid_prestamo_ids = prestamos_clean.select(F.col("id_prestamo").alias("_pre_id"))
valid_garante_ids = (
    clientes_clean.select(F.col("id_cliente").alias("_gar_id"))
    .unionByName(empresas_clean.select(F.col("id_empresa").alias("_gar_id")))
)

# Flag orphaned loan FK
garantias_flagged = garantias_raw.join(
    valid_prestamo_ids.withColumn("_loan_valid", F.lit(True)),
    garantias_raw["id_prestamo"] == valid_prestamo_ids["_pre_id"],
    how="left",
).drop("_pre_id")

# Flag orphaned guarantor FK
garantias_flagged = garantias_flagged.join(
    valid_garante_ids.withColumn("_gar_valid", F.lit(True)),
    garantias_flagged["id_garante"] == valid_garante_ids["_gar_id"],
    how="left",
).drop("_gar_id")

garantias_conditions = {
    "orphaned_loan_fk": F.col("_loan_valid").isNull(),
    "orphaned_guarantor_fk": F.col("_gar_valid").isNull(),
    "expired_but_active": (
        F.col("fecha_vencimiento").isNotNull()
        & (F.to_date(F.col("fecha_vencimiento")) < F.to_date(F.lit(REFERENCE_DATE)))
        & (F.upper(F.col("activa")) == "TRUE")
    ),
    "status_date_mismatch": (
        (F.upper(F.col("activa")) == "FALSE")
        & F.col("fecha_vencimiento").isNotNull()
        & (F.to_date(F.col("fecha_vencimiento")) > F.to_date(F.lit(REFERENCE_DATE)))
    ),
}

garantias_clean, garantias_rejected = validate_and_split(
    garantias_flagged, garantias_conditions, "id_garantia", "garantias"
)
garantias_clean = garantias_clean.drop("_loan_valid", "_gar_valid")

print("\nSample rejected garantias:")
garantias_rejected.select("id_garantia", "id_prestamo", "id_garante", "rejection_reasons").show(
    10, truncate=False
)

# COMMAND ----------

# --- Validate relaciones (6 embedded issues) ---
# Conditional FK validation: id_individuo is a CLIENT for ACCIONISTA/DIRECTOR rows
# but an EMPRESA for SUBSIDIARIA rows (dual-purpose column in the raw data).

rel_person = relaciones_raw.filter(F.col("tipo_relacion").isin("ACCIONISTA", "DIRECTOR"))
rel_subsidiary = relaciones_raw.filter(F.col("tipo_relacion") == "SUBSIDIARIA")

# -- ACCIONISTA/DIRECTOR: id_individuo must exist in clientes_clean
rel_person_flagged = rel_person.join(
    clientes_clean.select(F.col("id_cliente").alias("_cli_valid_id")),
    rel_person["id_individuo"] == F.col("_cli_valid_id"),
    how="left",
).withColumn(
    "orphaned_person_fk", F.col("_cli_valid_id").isNull()
).drop("_cli_valid_id")

# -- SUBSIDIARIA: id_individuo actually holds an empresa ID
rel_sub_flagged = rel_subsidiary.join(
    empresas_clean.select(F.col("id_empresa").alias("_emp_valid_id")),
    rel_subsidiary["id_individuo"] == F.col("_emp_valid_id"),
    how="left",
).withColumn(
    "orphaned_person_fk", F.col("_emp_valid_id").isNull()
).drop("_emp_valid_id")

# Re-union and validate id_empresa FK for ALL types
rel_all_flagged = rel_person_flagged.unionByName(rel_sub_flagged)
rel_all_flagged = rel_all_flagged.join(
    empresas_clean.select(F.col("id_empresa").alias("_emp_fk_id")),
    rel_all_flagged["id_empresa"] == F.col("_emp_fk_id"),
    how="left",
).withColumn(
    "orphaned_company_fk", F.col("_emp_fk_id").isNull()
).drop("_emp_fk_id")

relaciones_conditions = {
    "orphaned_person_fk": F.col("orphaned_person_fk"),
    "orphaned_company_fk": F.col("orphaned_company_fk"),
}

relaciones_clean, relaciones_rejected = validate_and_split(
    rel_all_flagged, relaciones_conditions, "id_relacion", "relaciones"
)
relaciones_clean = relaciones_clean.drop("orphaned_person_fk", "orphaned_company_fk")

print("\nSample rejected relaciones:")
relaciones_rejected.select(
    "id_relacion", "id_individuo", "id_empresa", "tipo_relacion", "rejection_reasons"
).show(10, truncate=False)

# COMMAND ----------

# --- Union all rejected records into a single audit table ---
# Standardize to common schema: id, entity_type, rejection_reasons

rej_clientes = clientes_rejected.select(
    F.col("id_cliente").alias("id"),
    F.lit("CLIENTE").alias("entity_type"),
    F.col("rejection_reasons"),
)
rej_empresas = empresas_rejected.select(
    F.col("id_empresa").alias("id"),
    F.lit("EMPRESA").alias("entity_type"),
    F.col("rejection_reasons"),
)
rej_prestamos = prestamos_rejected.select(
    F.col("id_prestamo").alias("id"),
    F.lit("PRESTAMO").alias("entity_type"),
    F.col("rejection_reasons"),
)
rej_garantias = garantias_rejected.select(
    F.col("id_garantia").alias("id"),
    F.lit("GARANTIA").alias("entity_type"),
    F.col("rejection_reasons"),
)
rej_relaciones = relaciones_rejected.select(
    F.col("id_relacion").alias("id"),
    F.lit("RELACION").alias("entity_type"),
    F.col("rejection_reasons"),
)

all_rejected = (
    rej_clientes
    .unionByName(rej_empresas)
    .unionByName(rej_prestamos)
    .unionByName(rej_garantias)
    .unionByName(rej_relaciones)
)

print(f"Total rejected records: {all_rejected.count()}")
all_rejected.show(20, truncate=False)

# COMMAND ----------

# --- Summary statistics ---
print("=== Rejection summary by entity type ===")
all_rejected.groupBy("entity_type").count().orderBy("entity_type").show()

# Explode pipe-delimited reasons to count individual rule triggers
print("=== Rejection reasons breakdown ===")
(
    all_rejected
    .withColumn("reason", F.explode(F.split(F.col("rejection_reasons"), " \\| ")))
    .filter(F.col("reason") != "")
    .groupBy("entity_type", "reason")
    .count()
    .orderBy("entity_type", F.desc("count"))
    .show(50, truncate=False)
)

# COMMAND ----------

# --- Write clean Parquet ---
# Overwrite mode so reruns are idempotent.
clientes_clean.write.mode("overwrite").parquet(f"{CLEAN_PATH}/clientes")
empresas_clean.write.mode("overwrite").parquet(f"{CLEAN_PATH}/empresas")
prestamos_clean.write.mode("overwrite").parquet(f"{CLEAN_PATH}/prestamos")
garantias_clean.write.mode("overwrite").parquet(f"{CLEAN_PATH}/garantias")
relaciones_clean.write.mode("overwrite").parquet(f"{CLEAN_PATH}/relaciones")

# Write unified rejected table
all_rejected.write.mode("overwrite").parquet(f"{REJECTED_PATH}/all_rejected")

print("Parquet written:")
for name in ["clientes", "empresas", "prestamos", "garantias", "relaciones"]:
    print(f"  {CLEAN_PATH}/{name}")
print(f"  {REJECTED_PATH}/all_rejected")

# COMMAND ----------

# --- Verification: conservation check ---
# For each entity: raw_count == clean_count + rejected_count.
# This is the fundamental invariant -- if it fails, we lost or duplicated records.

print("=== Conservation check: raw == clean + rejected ===\n")

checks = [
    ("clientes",   f"{RAW_PATH}/clientes_raw.csv",   schema_clientes,   f"{CLEAN_PATH}/clientes",   "CLIENTE"),
    ("empresas",   f"{RAW_PATH}/empresas_raw.csv",    schema_empresas,   f"{CLEAN_PATH}/empresas",   "EMPRESA"),
    ("prestamos",  f"{RAW_PATH}/prestamos_raw.csv",   schema_prestamos,  f"{CLEAN_PATH}/prestamos",  "PRESTAMO"),
    ("garantias",  f"{RAW_PATH}/garantias_raw.csv",   schema_garantias,  f"{CLEAN_PATH}/garantias",  "GARANTIA"),
    ("relaciones", f"{RAW_PATH}/relaciones_raw.csv",  schema_relaciones, f"{CLEAN_PATH}/relaciones", "RELACION"),
]

all_rejected_read = spark.read.parquet(f"{REJECTED_PATH}/all_rejected")
all_pass = True

for name, raw_path, schema, clean_path, etype in checks:
    raw_count = spark.read.option("header", "true").schema(schema).csv(raw_path).count()
    clean_count = spark.read.parquet(clean_path).count()
    rej_count = all_rejected_read.filter(F.col("entity_type") == etype).count()
    status = "PASS" if raw_count == clean_count + rej_count else "FAIL"
    if status == "FAIL":
        all_pass = False
    print(f"  {name:12s}  raw={raw_count:4d}  clean={clean_count:4d}  rejected={rej_count:3d}  "
          f"sum={clean_count + rej_count:4d}  [{status}]")

print(f"\nOverall: {'ALL PASS' if all_pass else 'FAILURES DETECTED -- investigate above'}")

# COMMAND ----------

# Unpersist cached DataFrames to free cluster memory
clientes_clean.unpersist()
empresas_clean.unpersist()
print("Cached DataFrames unpersisted.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## ETL Summary
# MAGIC
# MAGIC | Entity | Raw | Clean | Rejected | Corrections |
# MAGIC |--------|-----|-------|----------|-------------|
# MAGIC | clientes | 300 | ~270-280 | ~20-30 | 5 state codes standardized |
# MAGIC | empresas | 95 | ~93-95 | ~0-2 | 5 state codes standardized |
# MAGIC | prestamos | 466 | ~440-450 | ~16-26 | -- |
# MAGIC | garantias | 190 | ~170-180 | ~10-20 | -- |
# MAGIC | relaciones | 99 | ~93-97 | ~2-6 | -- |
# MAGIC
# MAGIC Exact counts depend on which records trigger multiple rules simultaneously.
# MAGIC The conservation check (cell 18) confirms raw == clean + rejected for every entity.
# MAGIC
# MAGIC **What this demonstrates:** PySpark validation using only `F.when()` chains and
# MAGIC distributed joins -- no UDFs, no driver-side collection, no `.toPandas()`.
# MAGIC The same pipeline handles 500 rows or 50 million with zero code changes.
