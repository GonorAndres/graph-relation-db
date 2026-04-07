"""
06_generate_neo4j_load.py
--------------------------
Generates Neo4J LOAD CSV Cypher scripts and minimally-validated CSVs.

Only strips records that would CRASH the load:
  - Orphaned FK references (edges pointing to nonexistent nodes)
  - Records with NULL primary keys

Everything else (negative income, bad scores, inconsistent states) stays
dirty. The PySpark ETL session (Phase 2) handles the real cleaning.

Output:
  data/clean/*.csv          -- Minimally validated CSVs for Neo4J
  neo4j/load_all.cypher     -- LOAD CSV Cypher commands
  neo4j/constraints.cypher  -- Uniqueness constraints (run first)
"""

import csv
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
CLEAN_DIR = Path(__file__).resolve().parent.parent / "data" / "clean"
NEO4J_DIR = Path(__file__).resolve().parent.parent / "neo4j"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------
def load_csv(filename):
    with open(RAW_DIR / filename, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(data, filename):
    if not data:
        return
    path = CLEAN_DIR / filename
    fieldnames = list(data[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    log.info(f"  Wrote {len(data)} rows to {path}")


# ---------------------------------------------------------------------------
# Minimal validation -- only fix what would crash Neo4J LOAD
# ---------------------------------------------------------------------------
def validate_for_load(clientes, empresas, prestamos, garantias, relaciones):
    """
    Strip orphaned FKs and NULL PKs. Nothing else.
    Returns (clean data, rejected records with reasons).
    """
    rejected = []

    # Valid node IDs -- these are the only entities that will exist as nodes
    valid_client_ids = {c["id_cliente"] for c in clientes if c["id_cliente"]}
    valid_empresa_ids = {e["id_empresa"] for e in empresas if e["id_empresa"]}
    valid_all_ids = valid_client_ids | valid_empresa_ids

    # --- Prestamos: remove orphaned id_titular ---
    # If id_titular doesn't match any client or empresa, the
    # TIENE_PRESTAMO edge would point to a nonexistent node.
    clean_prestamos = []
    for p in prestamos:
        if not p["id_prestamo"]:
            rejected.append({"entity": "prestamos", "id": "NULL",
                             "reason": "NULL primary key"})
            continue
        if p["id_titular"] not in valid_all_ids:
            rejected.append({"entity": "prestamos", "id": p["id_prestamo"],
                             "reason": f"Orphaned id_titular: {p['id_titular']}"})
            continue
        clean_prestamos.append(p)

    valid_prestamo_ids = {p["id_prestamo"] for p in clean_prestamos}

    # --- Garantias: remove orphaned id_prestamo and id_garante ---
    # Both ends of the GARANTIZA edge must exist as nodes.
    clean_garantias = []
    for g in garantias:
        if not g["id_garantia"]:
            rejected.append({"entity": "garantias", "id": "NULL",
                             "reason": "NULL primary key"})
            continue
        if g["id_prestamo"] not in valid_prestamo_ids:
            rejected.append({"entity": "garantias", "id": g["id_garantia"],
                             "reason": f"Orphaned id_prestamo: {g['id_prestamo']}"})
            continue
        if g["id_garante"] not in valid_all_ids:
            rejected.append({"entity": "garantias", "id": g["id_garantia"],
                             "reason": f"Orphaned id_garante: {g['id_garante']}"})
            continue
        clean_garantias.append(g)

    # --- Relaciones: remove orphaned id_individuo and id_empresa ---
    # For SUBSIDIARIA type, id_individuo is actually a child empresa ID.
    clean_relaciones = []
    for r in relaciones:
        if not r["id_relacion"]:
            rejected.append({"entity": "relaciones", "id": "NULL",
                             "reason": "NULL primary key"})
            continue
        if r["tipo_relacion"] == "SUBSIDIARIA":
            # Child empresa -> parent empresa
            if r["id_individuo"] not in valid_empresa_ids:
                rejected.append({"entity": "relaciones", "id": r["id_relacion"],
                                 "reason": f"Orphaned child empresa: {r['id_individuo']}"})
                continue
            if r["id_empresa"] not in valid_empresa_ids:
                rejected.append({"entity": "relaciones", "id": r["id_relacion"],
                                 "reason": f"Orphaned parent empresa: {r['id_empresa']}"})
                continue
        else:
            # Person -> empresa
            if r["id_individuo"] not in valid_client_ids:
                rejected.append({"entity": "relaciones", "id": r["id_relacion"],
                                 "reason": f"Orphaned id_individuo: {r['id_individuo']}"})
                continue
            if r["id_empresa"] not in valid_empresa_ids:
                rejected.append({"entity": "relaciones", "id": r["id_relacion"],
                                 "reason": f"Orphaned id_empresa: {r['id_empresa']}"})
                continue
        clean_relaciones.append(r)

    return (
        clientes,  # nodes pass through -- dirty fields won't crash LOAD
        empresas,
        clean_prestamos,
        clean_garantias,
        clean_relaciones,
        rejected,
    )


# ---------------------------------------------------------------------------
# Generate Cypher LOAD scripts
# ---------------------------------------------------------------------------
def generate_constraints():
    """Uniqueness constraints -- must run BEFORE loading data."""
    return """\
// ============================================================
// CreditGraph: Uniqueness Constraints
// Run this BEFORE load_all.cypher
// ============================================================

CREATE CONSTRAINT cliente_id IF NOT EXISTS
  FOR (c:ClienteIndividual) REQUIRE c.id_cliente IS UNIQUE;

CREATE CONSTRAINT empresa_id IF NOT EXISTS
  FOR (e:Empresa) REQUIRE e.id_empresa IS UNIQUE;

CREATE CONSTRAINT prestamo_id IF NOT EXISTS
  FOR (p:Prestamo) REQUIRE p.id_prestamo IS UNIQUE;
"""


def generate_load_cypher():
    """
    LOAD CSV Cypher commands.
    Assumes CSVs are in the Neo4J import directory or accessible via file:// URL.
    Adjust the path prefix if using Neo4J Desktop vs Docker vs Aura.
    """
    # The file:/// prefix assumes files are in Neo4J's import/ directory.
    # For local development: copy data/clean/*.csv to <neo4j>/import/
    return """\
// ============================================================
// CreditGraph: LOAD CSV Script
// ============================================================
// Prerequisites:
//   1. Run constraints.cypher first
//   2. Copy data/clean/*.csv to your Neo4J import/ directory
//   3. Run this script in Neo4J Browser or cypher-shell
//
// Note: raw data still contains quality issues (negative income,
// bad scores, inconsistent states). Only orphaned FKs were removed
// to prevent broken edges. Full cleaning is the PySpark ETL phase.
// ============================================================


// ------------------------------------------------------------
// STEP 1: Load Nodes
// ------------------------------------------------------------

// ClienteIndividual nodes (300 records)
LOAD CSV WITH HEADERS FROM 'file:///clientes_clean.csv' AS row
CREATE (c:ClienteIndividual {
  id_cliente:                   row.id_cliente,
  nombre_completo:              row.nombre_completo,
  curp:                         row.curp,
  fecha_nacimiento:             date(row.fecha_nacimiento),
  estado_residencia:            row.estado_residencia,
  nivel_ingresos:               toFloat(row.nivel_ingresos),
  antiguedad_cliente_meses:     toInteger(row.antiguedad_cliente_meses),
  score_buro:                   toFloat(row.score_buro),
  historico_incumplimientos:    toInteger(row.historico_incumplimientos),
  fecha_ultimo_incumplimiento:  CASE WHEN row.fecha_ultimo_incumplimiento <> ''
                                  THEN date(row.fecha_ultimo_incumplimiento)
                                  ELSE null END
});

// Empresa nodes
LOAD CSV WITH HEADERS FROM 'file:///empresas_clean.csv' AS row
CREATE (e:Empresa {
  id_empresa:           row.id_empresa,
  razon_social:         row.razon_social,
  rfc:                  row.rfc,
  sector:               row.sector,
  tamano:               row.tamano,
  ingresos_anuales_mxn: toFloat(row.ingresos_anuales_mxn),
  anos_operacion:       toInteger(row.anos_operacion),
  num_empleados:        toInteger(row.num_empleados),
  estado_registro:      row.estado_registro
});

// Prestamo nodes
LOAD CSV WITH HEADERS FROM 'file:///prestamos_clean.csv' AS row
CREATE (p:Prestamo {
  id_prestamo:                  row.id_prestamo,
  id_titular:                   row.id_titular,
  tipo_titular:                 row.tipo_titular,
  monto_original_mxn:           toFloat(row.monto_original_mxn),
  saldo_vigente_mxn:            toFloat(row.saldo_vigente_mxn),
  tasa_interes_anual:           toFloat(row.tasa_interes_anual),
  fecha_inicio:                 CASE WHEN row.fecha_inicio <> ''
                                  THEN date(row.fecha_inicio) ELSE null END,
  fecha_vencimiento:            CASE WHEN row.fecha_vencimiento <> ''
                                  THEN date(row.fecha_vencimiento) ELSE null END,
  estatus:                      row.estatus,
  dias_mora:                    toInteger(row.dias_mora),
  probabilidad_incumplimiento:  CASE WHEN row.probabilidad_incumplimiento <> ''
                                  THEN toFloat(row.probabilidad_incumplimiento)
                                  ELSE null END,
  score_version:                CASE WHEN row.score_version <> ''
                                  THEN row.score_version ELSE null END,
  score_fecha:                  CASE WHEN row.score_fecha <> ''
                                  THEN row.score_fecha ELSE null END
});


// ------------------------------------------------------------
// STEP 2: Load Relationships
// ------------------------------------------------------------

// TIENE_PRESTAMO: ClienteIndividual -> Prestamo
LOAD CSV WITH HEADERS FROM 'file:///prestamos_clean.csv' AS row
WITH row WHERE row.tipo_titular = 'INDIVIDUAL'
MATCH (c:ClienteIndividual {id_cliente: row.id_titular})
MATCH (p:Prestamo {id_prestamo: row.id_prestamo})
CREATE (c)-[:TIENE_PRESTAMO]->(p);

// TIENE_PRESTAMO: Empresa -> Prestamo
LOAD CSV WITH HEADERS FROM 'file:///prestamos_clean.csv' AS row
WITH row WHERE row.tipo_titular = 'EMPRESA'
MATCH (e:Empresa {id_empresa: row.id_titular})
MATCH (p:Prestamo {id_prestamo: row.id_prestamo})
CREATE (e)-[:TIENE_PRESTAMO]->(p);

// GARANTIZA: guarantor -> Prestamo
LOAD CSV WITH HEADERS FROM 'file:///garantias_clean.csv' AS row
MATCH (p:Prestamo {id_prestamo: row.id_prestamo})
OPTIONAL MATCH (c:ClienteIndividual {id_cliente: row.id_garante})
OPTIONAL MATCH (e:Empresa {id_empresa: row.id_garante})
WITH row, p, coalesce(c, e) AS garante
WHERE garante IS NOT NULL
CREATE (garante)-[:GARANTIZA {
  id_garantia:          row.id_garantia,
  tipo_garantia:        row.tipo_garantia,
  cobertura_porcentaje: toFloat(row.cobertura_porcentaje),
  fecha_inicio:         CASE WHEN row.fecha_inicio <> ''
                          THEN date(row.fecha_inicio) ELSE null END,
  fecha_vencimiento:    CASE WHEN row.fecha_vencimiento <> ''
                          THEN date(row.fecha_vencimiento) ELSE null END,
  activa:               row.activa = 'True'
}]->(p);

// ES_ACCIONISTA_DE / ES_DIRECTOR_DE: ClienteIndividual -> Empresa
LOAD CSV WITH HEADERS FROM 'file:///relaciones_clean.csv' AS row
WITH row WHERE row.tipo_relacion IN ['ACCIONISTA', 'DIRECTOR']
MATCH (c:ClienteIndividual {id_cliente: row.id_individuo})
MATCH (e:Empresa {id_empresa: row.id_empresa})
FOREACH (_ IN CASE WHEN row.tipo_relacion = 'ACCIONISTA' THEN [1] ELSE [] END |
  CREATE (c)-[:ES_ACCIONISTA_DE {
    porcentaje_participacion: toFloat(row.porcentaje_participacion),
    fecha_inicio:             date(row.fecha_inicio),
    activa:                   row.activa = 'True'
  }]->(e)
)
FOREACH (_ IN CASE WHEN row.tipo_relacion = 'DIRECTOR' THEN [1] ELSE [] END |
  CREATE (c)-[:ES_DIRECTOR_DE {
    fecha_inicio: date(row.fecha_inicio),
    activa:       row.activa = 'True'
  }]->(e)
);

// ES_SUBSIDIARIA_DE: child Empresa -> parent Empresa
LOAD CSV WITH HEADERS FROM 'file:///relaciones_clean.csv' AS row
WITH row WHERE row.tipo_relacion = 'SUBSIDIARIA'
MATCH (child:Empresa {id_empresa: row.id_individuo})
MATCH (parent:Empresa {id_empresa: row.id_empresa})
CREATE (child)-[:ES_SUBSIDIARIA_DE {
  porcentaje_participacion: toFloat(row.porcentaje_participacion),
  fecha_inicio:             date(row.fecha_inicio),
  activa:                   row.activa = 'True'
}]->(parent);


// ------------------------------------------------------------
// STEP 3: Verification queries
// ------------------------------------------------------------

// Count all node types
MATCH (n) RETURN labels(n)[0] AS type, count(n) AS count ORDER BY type;

// Count all relationship types
MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS count ORDER BY type;

// Verify scenario 2: circular guarantee
MATCH (c1:ClienteIndividual)-[:GARANTIZA]->(p1:Prestamo)<-[:TIENE_PRESTAMO]-(c2:ClienteIndividual)
      -[:GARANTIZA]->(p2:Prestamo)<-[:TIENE_PRESTAMO]-(c3:ClienteIndividual)
      -[:GARANTIZA]->(p3:Prestamo)<-[:TIENE_PRESTAMO]-(c1)
RETURN c1.nombre_completo, c2.nombre_completo, c3.nombre_completo;
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    NEO4J_DIR.mkdir(parents=True, exist_ok=True)

    log.info("=" * 60)
    log.info("Loading raw CSVs")
    log.info("=" * 60)

    clientes = load_csv("clientes_raw.csv")
    empresas = load_csv("empresas_raw.csv")
    prestamos = load_csv("prestamos_raw.csv")
    garantias = load_csv("garantias_raw.csv")
    relaciones = load_csv("relaciones_raw.csv")

    log.info(f"  Raw: {len(clientes)} clientes, {len(empresas)} empresas, "
             f"{len(prestamos)} prestamos, {len(garantias)} garantias, "
             f"{len(relaciones)} relaciones")

    # Validate -- only strip what would crash Neo4J
    log.info("\n" + "=" * 60)
    log.info("Minimal validation (orphaned FKs only)")
    log.info("=" * 60)

    (clean_clientes, clean_empresas, clean_prestamos,
     clean_garantias, clean_relaciones, rejected) = validate_for_load(
        clientes, empresas, prestamos, garantias, relaciones
    )

    log.info(f"  Rejected: {len(rejected)} records")
    for r in rejected:
        log.info(f"    {r['entity']} {r['id']}: {r['reason']}")

    log.info(f"\n  Clean: {len(clean_clientes)} clientes, {len(clean_empresas)} empresas, "
             f"{len(clean_prestamos)} prestamos, {len(clean_garantias)} garantias, "
             f"{len(clean_relaciones)} relaciones")

    # Write clean CSVs
    log.info("\n" + "=" * 60)
    log.info("Writing clean CSVs")
    log.info("=" * 60)
    write_csv(clean_clientes, "clientes_clean.csv")
    write_csv(clean_empresas, "empresas_clean.csv")
    write_csv(clean_prestamos, "prestamos_clean.csv")
    write_csv(clean_garantias, "garantias_clean.csv")
    write_csv(clean_relaciones, "relaciones_clean.csv")

    # Write rejected records
    if rejected:
        rejected_path = CLEAN_DIR / "rejected_records.csv"
        with open(rejected_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["entity", "id", "reason"])
            writer.writeheader()
            writer.writerows(rejected)
        log.info(f"  Wrote {len(rejected)} rejected records to {rejected_path}")

    # Generate Cypher scripts
    log.info("\n" + "=" * 60)
    log.info("Generating Cypher scripts")
    log.info("=" * 60)

    constraints_path = NEO4J_DIR / "constraints.cypher"
    with open(constraints_path, "w", encoding="utf-8") as f:
        f.write(generate_constraints())
    log.info(f"  Wrote {constraints_path}")

    load_path = NEO4J_DIR / "load_all.cypher"
    with open(load_path, "w", encoding="utf-8") as f:
        f.write(generate_load_cypher())
    log.info(f"  Wrote {load_path}")

    # Summary
    log.info("\n" + "=" * 60)
    log.info("Done. Next steps:")
    log.info("  1. Install Neo4J (Desktop, Docker, or Aura)")
    log.info("  2. Copy data/clean/*.csv to <neo4j>/import/")
    log.info("  3. Run neo4j/constraints.cypher")
    log.info("  4. Run neo4j/load_all.cypher")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
