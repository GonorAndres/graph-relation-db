"""
07_load_neo4j.py
----------------
Loads clean CSV data into Neo4J AuraDB using the Python driver.

AuraDB doesn't have a local import/ directory, so we can't use LOAD CSV.
Instead, we read the CSVs in Python and use UNWIND to batch-insert records.

UNWIND is the production pattern for batch writes:
  - One Cypher call with UNWIND $batch inserts N records
  - vs N separate session.run() calls (one per record)
  - Same result, ~100x faster, one transaction instead of N

Order matters:
  1. Create constraints (uniqueness on PKs)
  2. Create nodes (ClienteIndividual, Empresa, Prestamo)
  3. Create relationships (TIENE_PRESTAMO, GARANTIZA, ES_ACCIONISTA_DE, etc.)
"""

import csv
import logging
import time
from pathlib import Path

from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CLEAN_DIR = Path(__file__).resolve().parent.parent / "data" / "clean"

# AuraDB credentials
URI = "neo4j+s://1c09a89b.databases.neo4j.io"
USERNAME = "1c09a89b"
PASSWORD = "nkK0o_ciyV2KQL9MV8BYpBJb3B1p3CjJ2ML10bJsn24"

BATCH_SIZE = 100  # records per UNWIND batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_csv(filename):
    with open(CLEAN_DIR / filename, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def batch_execute(session, cypher, data, batch_size=BATCH_SIZE):
    """Execute a Cypher UNWIND in batches."""
    total = 0
    for i in range(0, len(data), batch_size):
        batch = data[i:i + batch_size]
        session.run(cypher, batch=batch)
        total += len(batch)
    return total


# ---------------------------------------------------------------------------
# Step 1: Constraints
# ---------------------------------------------------------------------------
def create_constraints(session):
    constraints = [
        "CREATE CONSTRAINT cliente_id IF NOT EXISTS FOR (c:ClienteIndividual) REQUIRE c.id_cliente IS UNIQUE",
        "CREATE CONSTRAINT empresa_id IF NOT EXISTS FOR (e:Empresa) REQUIRE e.id_empresa IS UNIQUE",
        "CREATE CONSTRAINT prestamo_id IF NOT EXISTS FOR (p:Prestamo) REQUIRE p.id_prestamo IS UNIQUE",
    ]
    for cypher in constraints:
        session.run(cypher)
    log.info("  Created 3 uniqueness constraints")


# ---------------------------------------------------------------------------
# Step 2: Nodes
# ---------------------------------------------------------------------------
def load_clientes(session):
    data = load_csv("clientes_clean.csv")

    # Convert types in Python before sending to Neo4J
    for row in data:
        row["nivel_ingresos"] = float(row["nivel_ingresos"]) if row["nivel_ingresos"] else None
        row["antiguedad_cliente_meses"] = int(row["antiguedad_cliente_meses"]) if row["antiguedad_cliente_meses"] else None
        row["score_buro"] = float(row["score_buro"]) if row["score_buro"] else None
        row["historico_incumplimientos"] = int(row["historico_incumplimientos"]) if row["historico_incumplimientos"] else None
        # Empty strings -> None for optional fields
        row["nombre_completo"] = row["nombre_completo"] or None
        row["estado_residencia"] = row["estado_residencia"] or None
        row["fecha_ultimo_incumplimiento"] = row["fecha_ultimo_incumplimiento"] or None

    cypher = """
    UNWIND $batch AS row
    CREATE (c:ClienteIndividual {
        id_cliente:                  row.id_cliente,
        nombre_completo:             row.nombre_completo,
        curp:                        row.curp,
        fecha_nacimiento:            date(row.fecha_nacimiento),
        estado_residencia:           row.estado_residencia,
        nivel_ingresos:              row.nivel_ingresos,
        antiguedad_cliente_meses:    row.antiguedad_cliente_meses,
        score_buro:                  row.score_buro,
        historico_incumplimientos:   row.historico_incumplimientos,
        fecha_ultimo_incumplimiento: CASE WHEN row.fecha_ultimo_incumplimiento IS NOT NULL
                                       THEN date(row.fecha_ultimo_incumplimiento)
                                       ELSE null END
    })
    """
    count = batch_execute(session, cypher, data)
    log.info(f"  Loaded {count} ClienteIndividual nodes")


def load_empresas(session):
    data = load_csv("empresas_clean.csv")

    for row in data:
        row["ingresos_anuales_mxn"] = float(row["ingresos_anuales_mxn"]) if row["ingresos_anuales_mxn"] else None
        row["anos_operacion"] = int(row["anos_operacion"]) if row["anos_operacion"] else None
        row["num_empleados"] = int(row["num_empleados"]) if row["num_empleados"] else None
        row["razon_social"] = row["razon_social"] or None
        row["estado_registro"] = row["estado_registro"] or None

    cypher = """
    UNWIND $batch AS row
    CREATE (e:Empresa {
        id_empresa:          row.id_empresa,
        razon_social:        row.razon_social,
        rfc:                 row.rfc,
        sector:              row.sector,
        tamano:              row.tamano,
        ingresos_anuales_mxn: row.ingresos_anuales_mxn,
        anos_operacion:      row.anos_operacion,
        num_empleados:       row.num_empleados,
        estado_registro:     row.estado_registro
    })
    """
    count = batch_execute(session, cypher, data)
    log.info(f"  Loaded {count} Empresa nodes")


def load_prestamos(session):
    data = load_csv("prestamos_clean.csv")

    for row in data:
        row["monto_original_mxn"] = float(row["monto_original_mxn"]) if row["monto_original_mxn"] else None
        row["saldo_vigente_mxn"] = float(row["saldo_vigente_mxn"]) if row["saldo_vigente_mxn"] else None
        row["tasa_interes_anual"] = float(row["tasa_interes_anual"]) if row["tasa_interes_anual"] else None
        row["dias_mora"] = int(row["dias_mora"]) if row["dias_mora"] else 0
        row["probabilidad_incumplimiento"] = float(row["probabilidad_incumplimiento"]) if row["probabilidad_incumplimiento"] else None
        row["fecha_inicio"] = row["fecha_inicio"] or None
        row["fecha_vencimiento"] = row["fecha_vencimiento"] or None
        row["score_version"] = row["score_version"] or None
        row["score_fecha"] = row["score_fecha"] or None

    cypher = """
    UNWIND $batch AS row
    CREATE (p:Prestamo {
        id_prestamo:                 row.id_prestamo,
        id_titular:                  row.id_titular,
        tipo_titular:                row.tipo_titular,
        monto_original_mxn:          row.monto_original_mxn,
        saldo_vigente_mxn:           row.saldo_vigente_mxn,
        tasa_interes_anual:          row.tasa_interes_anual,
        fecha_inicio:                CASE WHEN row.fecha_inicio IS NOT NULL
                                       THEN date(row.fecha_inicio) ELSE null END,
        fecha_vencimiento:           CASE WHEN row.fecha_vencimiento IS NOT NULL
                                       THEN date(row.fecha_vencimiento) ELSE null END,
        estatus:                     row.estatus,
        dias_mora:                   row.dias_mora,
        probabilidad_incumplimiento: row.probabilidad_incumplimiento,
        score_version:               row.score_version,
        score_fecha:                 row.score_fecha
    })
    """
    count = batch_execute(session, cypher, data)
    log.info(f"  Loaded {count} Prestamo nodes")


# ---------------------------------------------------------------------------
# Step 3: Relationships
# ---------------------------------------------------------------------------
def load_tiene_prestamo(session):
    """Create TIENE_PRESTAMO edges: (ClienteIndividual|Empresa) -> Prestamo"""
    data = load_csv("prestamos_clean.csv")

    # Individual loans
    individual = [r for r in data if r["tipo_titular"] == "INDIVIDUAL"]
    cypher_ind = """
    UNWIND $batch AS row
    MATCH (c:ClienteIndividual {id_cliente: row.id_titular})
    MATCH (p:Prestamo {id_prestamo: row.id_prestamo})
    CREATE (c)-[:TIENE_PRESTAMO]->(p)
    """
    count_ind = batch_execute(session, cypher_ind, individual)

    # Corporate loans
    corporate = [r for r in data if r["tipo_titular"] == "EMPRESA"]
    cypher_corp = """
    UNWIND $batch AS row
    MATCH (e:Empresa {id_empresa: row.id_titular})
    MATCH (p:Prestamo {id_prestamo: row.id_prestamo})
    CREATE (e)-[:TIENE_PRESTAMO]->(p)
    """
    count_corp = batch_execute(session, cypher_corp, corporate)
    log.info(f"  Created {count_ind + count_corp} TIENE_PRESTAMO edges ({count_ind} individual, {count_corp} corporate)")


def load_garantiza(session):
    """Create GARANTIZA edges: (guarantor) -> Prestamo"""
    data = load_csv("garantias_clean.csv")

    for row in data:
        row["cobertura_porcentaje"] = float(row["cobertura_porcentaje"]) if row["cobertura_porcentaje"] else None
        row["activa_bool"] = row["activa"] == "True"
        row["fecha_inicio_val"] = row["fecha_inicio"] or None
        row["fecha_vencimiento_val"] = row["fecha_vencimiento"] or None

    # Try matching guarantor as ClienteIndividual first, then Empresa
    cypher = """
    UNWIND $batch AS row
    MATCH (p:Prestamo {id_prestamo: row.id_prestamo})
    OPTIONAL MATCH (c:ClienteIndividual {id_cliente: row.id_garante})
    OPTIONAL MATCH (e:Empresa {id_empresa: row.id_garante})
    WITH row, p, coalesce(c, e) AS garante
    WHERE garante IS NOT NULL
    CREATE (garante)-[:GARANTIZA {
        id_garantia:          row.id_garantia,
        tipo_garantia:        row.tipo_garantia,
        cobertura_porcentaje: row.cobertura_porcentaje,
        fecha_inicio:         CASE WHEN row.fecha_inicio_val IS NOT NULL
                                THEN date(row.fecha_inicio_val) ELSE null END,
        fecha_vencimiento:    CASE WHEN row.fecha_vencimiento_val IS NOT NULL
                                THEN date(row.fecha_vencimiento_val) ELSE null END,
        activa:               row.activa_bool
    }]->(p)
    """
    count = batch_execute(session, cypher, data)
    log.info(f"  Created {count} GARANTIZA edges (batch sent, actual may be fewer if some garantes not found)")


def load_relaciones(session):
    """Create ES_ACCIONISTA_DE, ES_DIRECTOR_DE, ES_SUBSIDIARIA_DE edges."""
    data = load_csv("relaciones_clean.csv")

    for row in data:
        row["porcentaje_val"] = float(row["porcentaje_participacion"]) if row["porcentaje_participacion"] else None
        row["activa_bool"] = row["activa"] == "True"
        row["fecha_inicio_val"] = row["fecha_inicio"] or None

    # Person -> Empresa (ACCIONISTA)
    accionistas = [r for r in data if r["tipo_relacion"] == "ACCIONISTA"]
    cypher_acc = """
    UNWIND $batch AS row
    MATCH (c:ClienteIndividual {id_cliente: row.id_individuo})
    MATCH (e:Empresa {id_empresa: row.id_empresa})
    CREATE (c)-[:ES_ACCIONISTA_DE {
        porcentaje_participacion: row.porcentaje_val,
        fecha_inicio:             CASE WHEN row.fecha_inicio_val IS NOT NULL
                                    THEN date(row.fecha_inicio_val) ELSE null END,
        activa:                   row.activa_bool
    }]->(e)
    """
    count_acc = batch_execute(session, cypher_acc, accionistas)

    # Person -> Empresa (DIRECTOR)
    directores = [r for r in data if r["tipo_relacion"] == "DIRECTOR"]
    cypher_dir = """
    UNWIND $batch AS row
    MATCH (c:ClienteIndividual {id_cliente: row.id_individuo})
    MATCH (e:Empresa {id_empresa: row.id_empresa})
    CREATE (c)-[:ES_DIRECTOR_DE {
        fecha_inicio: CASE WHEN row.fecha_inicio_val IS NOT NULL
                        THEN date(row.fecha_inicio_val) ELSE null END,
        activa:       row.activa_bool
    }]->(e)
    """
    count_dir = batch_execute(session, cypher_dir, directores)

    # Empresa -> Empresa (SUBSIDIARIA)
    subsidiarias = [r for r in data if r["tipo_relacion"] == "SUBSIDIARIA"]
    cypher_sub = """
    UNWIND $batch AS row
    MATCH (child:Empresa {id_empresa: row.id_individuo})
    MATCH (parent:Empresa {id_empresa: row.id_empresa})
    CREATE (child)-[:ES_SUBSIDIARIA_DE {
        porcentaje_participacion: row.porcentaje_val,
        fecha_inicio:             CASE WHEN row.fecha_inicio_val IS NOT NULL
                                    THEN date(row.fecha_inicio_val) ELSE null END,
        activa:                   row.activa_bool
    }]->(parent)
    """
    count_sub = batch_execute(session, cypher_sub, subsidiarias)

    log.info(f"  Created {count_acc} ES_ACCIONISTA_DE, {count_dir} ES_DIRECTOR_DE, {count_sub} ES_SUBSIDIARIA_DE edges")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def verify_graph(session):
    """Run verification queries to confirm the graph loaded correctly."""

    # Node counts
    result = session.run("MATCH (n) RETURN labels(n)[0] AS type, count(n) AS count ORDER BY type")
    log.info("\n  Node counts:")
    for record in result:
        log.info(f"    {record['type']}: {record['count']}")

    # Relationship counts
    result = session.run("MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS count ORDER BY type")
    log.info("\n  Relationship counts:")
    for record in result:
        log.info(f"    {record['type']}: {record['count']}")

    # Scenario 2 verification: circular guarantee
    result = session.run("""
        MATCH (c1:ClienteIndividual)-[:GARANTIZA]->(p1:Prestamo)
              <-[:TIENE_PRESTAMO]-(c2:ClienteIndividual)
              -[:GARANTIZA]->(p2:Prestamo)
              <-[:TIENE_PRESTAMO]-(c3:ClienteIndividual)
              -[:GARANTIZA]->(p3:Prestamo)
              <-[:TIENE_PRESTAMO]-(c1)
        WHERE c1 <> c2 AND c2 <> c3 AND c1 <> c3
        RETURN c1.nombre_completo AS person1,
               c2.nombre_completo AS person2,
               c3.nombre_completo AS person3
        LIMIT 1
    """)
    record = result.single()
    if record:
        log.info(f"\n  Scenario 2 (circular guarantee) VERIFIED:")
        log.info(f"    {record['person1']} -> {record['person2']} -> {record['person3']} -> cycle")
    else:
        log.info("\n  Scenario 2: no circular guarantee found (check data)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info("=" * 60)
    log.info("Connecting to Neo4J AuraDB")
    log.info("=" * 60)

    driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))
    driver.verify_connectivity()
    log.info("  Connected")

    with driver.session() as session:
        # Clear any existing data
        log.info("\n" + "=" * 60)
        log.info("Clearing existing data")
        log.info("=" * 60)
        session.run("MATCH (n) DETACH DELETE n")
        log.info("  Cleared")

        # Constraints
        log.info("\n" + "=" * 60)
        log.info("Step 1: Creating constraints")
        log.info("=" * 60)
        create_constraints(session)

        # Nodes
        log.info("\n" + "=" * 60)
        log.info("Step 2: Loading nodes")
        log.info("=" * 60)
        load_clientes(session)
        load_empresas(session)
        load_prestamos(session)

        # Relationships
        log.info("\n" + "=" * 60)
        log.info("Step 3: Loading relationships")
        log.info("=" * 60)
        load_tiene_prestamo(session)
        load_garantiza(session)
        load_relaciones(session)

        # Verify
        log.info("\n" + "=" * 60)
        log.info("Step 4: Verification")
        log.info("=" * 60)
        verify_graph(session)

    driver.close()
    log.info("\n" + "=" * 60)
    log.info("Done. Graph loaded into AuraDB.")
    log.info("Open Neo4J Browser to explore: https://console.neo4j.io")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
