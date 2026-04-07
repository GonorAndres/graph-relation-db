"""
04_embed_scenarios.py
---------------------
Plants 5 structural scenarios into the raw CSVs. Each scenario demonstrates
a graph capability that standard SQL cannot replicate.

The script modifies data/raw/*.csv IN PLACE -- it reads, appends/modifies
records, and writes back. Uses existing entity IDs where possible.

Scenarios:
  1. Guarantee chain depth 3: A guarantees B's loan, B guarantees C's loan,
     C is VENCIDO. Demonstrates [:GARANTIZA*1..4] variable-length traversal.

  2. Circular guarantee: X→Y→Z→X, all ACTIVO. Illegal under CNBV Circular
     3/2012. Demonstrates cycle detection -- impossible in standard SQL.

  3. Corporate contagion hub: 1 empresa (REESTRUCTURADO) with 5 shareholders
     who cross-guarantee personal loans. Demonstrates multi-hop contagion.

  4. Shared director: 1 person directs 2 companies, both with active loans.
     "Partes relacionadas" concentration flag. Uses REAL topology from PSC.

  5. Unsecured high-PD loans: 15 active loans with no guarantor, high risk
     indicators. Demonstrates relationship absence + property filter query.

Output: modified data/raw/*.csv files + data/source/scenario_manifest.json
"""

import csv
import json
import logging
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
SOURCE_DIR = Path(__file__).resolve().parent.parent / "data" / "source"
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------
def load_csv(filename: str) -> list[dict]:
    with open(RAW_DIR / filename, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(data: list[dict], filename: str):
    if not data:
        return
    path = RAW_DIR / filename
    fieldnames = list(data[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    log.info(f"  Wrote {len(data)} rows to {path}")


def next_id(prefix: str, existing: list[dict], id_field: str) -> str:
    """Generate the next sequential ID for a given prefix."""
    max_num = 0
    for row in existing:
        val = row[id_field]
        if val.startswith(prefix):
            try:
                num = int(val.split("-")[1])
                max_num = max(max_num, num)
            except (IndexError, ValueError):
                pass
    return f"{prefix}{max_num + 1:05d}"


# ---------------------------------------------------------------------------
# Scenario 1: Guarantee chain depth 3
# ---------------------------------------------------------------------------
def embed_scenario_1(clientes, empresas, prestamos, garantias):
    """
    Chain: CLI-00010 guarantees CLI-00011's loan,
           CLI-00011 guarantees CLI-00012's loan,
           CLI-00012's loan is VENCIDO (45 dias_mora).

    This means if CLI-00012 defaults, the guarantee chain exposes
    CLI-00011, which exposes CLI-00010. Three hops.
    """
    log.info("Scenario 1: Guarantee chain depth 3")

    chain_clients = ["CLI-00010", "CLI-00011", "CLI-00012"]

    # Ensure each has an active loan (find or create)
    chain_loans = {}
    for cid in chain_clients:
        existing = [p for p in prestamos if p["id_titular"] == cid and p["estatus"] in ("ACTIVO", "VENCIDO")]
        if existing:
            chain_loans[cid] = existing[0]["id_prestamo"]
        else:
            new_id = next_id("PRE-", prestamos, "id_prestamo")
            prestamos.append({
                "id_prestamo": new_id,
                "id_titular": cid,
                "tipo_titular": "INDIVIDUAL",
                "monto_original_mxn": round(float(np.random.lognormal(12.0, 0.8)), 2),
                "saldo_vigente_mxn": round(float(np.random.lognormal(11.5, 0.8)), 2),
                "tasa_interes_anual": round(random.uniform(0.10, 0.30), 4),
                "fecha_inicio": (date.today() - timedelta(days=400)).isoformat(),
                "fecha_vencimiento": (date.today() + timedelta(days=600)).isoformat(),
                "estatus": "ACTIVO",
                "dias_mora": 0,
                "probabilidad_incumplimiento": "",
                "score_version": "",
                "score_fecha": "",
            })
            chain_loans[cid] = new_id
            log.info(f"  Created loan {new_id} for {cid}")

    # Make CLI-00012's loan VENCIDO
    for p in prestamos:
        if p["id_prestamo"] == chain_loans["CLI-00012"]:
            p["estatus"] = "VENCIDO"
            p["dias_mora"] = 45
            log.info(f"  Set {p['id_prestamo']} to VENCIDO (45 dias_mora)")

    # Create guarantee chain: 10 guarantees 11's loan, 11 guarantees 12's loan
    chain_edges = [
        ("CLI-00010", chain_loans["CLI-00011"]),
        ("CLI-00011", chain_loans["CLI-00012"]),
    ]
    for garante, prestamo in chain_edges:
        # Check if guarantee already exists
        exists = any(
            g["id_garante"] == garante and g["id_prestamo"] == prestamo
            for g in garantias
        )
        if not exists:
            new_id = next_id("GAR-", garantias, "id_garantia")
            garantias.append({
                "id_garantia": new_id,
                "id_prestamo": prestamo,
                "id_garante": garante,
                "tipo_garantia": "AVAL",
                "cobertura_porcentaje": 0.80,
                "fecha_inicio": (date.today() - timedelta(days=300)).isoformat(),
                "fecha_vencimiento": (date.today() + timedelta(days=700)).isoformat(),
                "activa": True,
            })
            log.info(f"  Created guarantee: {garante} -> loan {prestamo}")

    scenario_info = {
        "name": "Guarantee chain depth 3",
        "entities": chain_clients,
        "loans": list(chain_loans.values()),
        "chain": "CLI-00010 -[guarantees]-> CLI-00011's loan -[guarantees]-> CLI-00012's loan (VENCIDO)",
        "cypher_query": "MATCH path = (c:ClienteIndividual)-[:GARANTIZA*1..4]->(p:Prestamo {estatus:'VENCIDO'}) RETURN path",
        "why_sql_cant": "SQL requires one JOIN per hop, and the depth (3) is not known in advance. Cypher traverses variable depth with *1..4.",
        "crisis_parallel": "AIG guarantee chains on CDOs -- depth was unknowable until the underlying asset failed.",
    }
    log.info(f"  Chain: {scenario_info['chain']}")
    return scenario_info


# ---------------------------------------------------------------------------
# Scenario 2: Circular guarantee (illegal)
# ---------------------------------------------------------------------------
def embed_scenario_2(clientes, empresas, prestamos, garantias):
    """
    Cycle: CLI-00020 guarantees CLI-00021's loan,
           CLI-00021 guarantees CLI-00022's loan,
           CLI-00022 guarantees CLI-00020's loan.

    All loans are ACTIVO. The guarantees cancel each other out --
    fictitious coverage. Illegal under CNBV Circular 3/2012.
    """
    log.info("Scenario 2: Circular guarantee (illegal)")

    cycle_clients = ["CLI-00020", "CLI-00021", "CLI-00022"]

    # Ensure each has an active loan
    cycle_loans = {}
    for cid in cycle_clients:
        existing = [p for p in prestamos if p["id_titular"] == cid and p["estatus"] == "ACTIVO"]
        if existing:
            cycle_loans[cid] = existing[0]["id_prestamo"]
        else:
            new_id = next_id("PRE-", prestamos, "id_prestamo")
            prestamos.append({
                "id_prestamo": new_id,
                "id_titular": cid,
                "tipo_titular": "INDIVIDUAL",
                "monto_original_mxn": round(float(np.random.lognormal(12.0, 0.8)), 2),
                "saldo_vigente_mxn": round(float(np.random.lognormal(11.5, 0.8)), 2),
                "tasa_interes_anual": round(random.uniform(0.10, 0.25), 4),
                "fecha_inicio": (date.today() - timedelta(days=500)).isoformat(),
                "fecha_vencimiento": (date.today() + timedelta(days=500)).isoformat(),
                "estatus": "ACTIVO",
                "dias_mora": 0,
                "probabilidad_incumplimiento": "",
                "score_version": "",
                "score_fecha": "",
            })
            cycle_loans[cid] = new_id
            log.info(f"  Created loan {new_id} for {cid}")

    # Create circular guarantee: 20→21's loan, 21→22's loan, 22→20's loan
    cycle_edges = [
        ("CLI-00020", cycle_loans["CLI-00021"]),
        ("CLI-00021", cycle_loans["CLI-00022"]),
        ("CLI-00022", cycle_loans["CLI-00020"]),
    ]
    for garante, prestamo in cycle_edges:
        exists = any(
            g["id_garante"] == garante and g["id_prestamo"] == prestamo
            for g in garantias
        )
        if not exists:
            new_id = next_id("GAR-", garantias, "id_garantia")
            garantias.append({
                "id_garantia": new_id,
                "id_prestamo": prestamo,
                "id_garante": garante,
                "tipo_garantia": "AVAL",
                "cobertura_porcentaje": 1.00,
                "fecha_inicio": (date.today() - timedelta(days=200)).isoformat(),
                "fecha_vencimiento": (date.today() + timedelta(days=800)).isoformat(),
                "activa": True,
            })
            log.info(f"  Created circular guarantee: {garante} -> loan {prestamo}")

    scenario_info = {
        "name": "Circular guarantee (illegal)",
        "entities": cycle_clients,
        "loans": list(cycle_loans.values()),
        "cycle": "CLI-00020 -> CLI-00021 -> CLI-00022 -> CLI-00020",
        "cypher_query": "MATCH (c)-[:GARANTIZA]->(p:Prestamo)<-[:TIENE_PRESTAMO]-(c2)-[:GARANTIZA]->(p2:Prestamo)<-[:TIENE_PRESTAMO]-(c3)-[:GARANTIZA]->(p3:Prestamo)<-[:TIENE_PRESTAMO]-(c) RETURN c, c2, c3",
        "why_sql_cant": "Cycle detection at arbitrary depth requires recursive CTEs with cycle-check conditions. In practice, SQL implementations break above depth 3. Cypher detects cycles natively.",
        "crisis_parallel": "AIG insured CDO tranches backed by mortgages AIG had also insured -- circular risk. When the underlying failed, the 'guarantee' was worthless because the guarantor was exposed to the same risk.",
        "regulation": "CNBV Circular 3/2012 prohibits guarantee structures where coverage is fictitious due to circular dependency.",
    }
    return scenario_info


# ---------------------------------------------------------------------------
# Scenario 3: Corporate contagion hub
# ---------------------------------------------------------------------------
def embed_scenario_3(clientes, empresas, prestamos, garantias, relaciones):
    """
    Empresa EMP-00031 (already has 2 real shared directors from PSC topology)
    becomes a contagion hub:
    - Status: REESTRUCTURADO
    - 5 shareholders (2 real from PSC + 3 added)
    - 2 shareholders cross-guarantee each other's personal loans
    - If EMP-00031 fails, all 5 shareholders are exposed
    """
    log.info("Scenario 3: Corporate contagion hub")

    hub_empresa = "EMP-00031"  # HARI MASA SA DE CV -- already has 2 directors

    # Existing directors from real topology
    existing_dirs = [r["id_individuo"] for r in relaciones if r["id_empresa"] == hub_empresa]
    log.info(f"  Existing directors of {hub_empresa}: {existing_dirs}")

    # Add 3 more shareholders
    new_shareholders = ["CLI-00030", "CLI-00031", "CLI-00032"]
    for cid in new_shareholders:
        exists = any(
            r["id_individuo"] == cid and r["id_empresa"] == hub_empresa
            for r in relaciones
        )
        if not exists:
            new_id = next_id("REL-", relaciones, "id_relacion")
            relaciones.append({
                "id_relacion": new_id,
                "id_individuo": cid,
                "id_empresa": hub_empresa,
                "tipo_relacion": "ACCIONISTA",
                "porcentaje_participacion": round(random.uniform(0.05, 0.20), 2),
                "fecha_inicio": (date.today() - timedelta(days=random.randint(365, 2000))).isoformat(),
                "fecha_fin": "",
                "activa": True,
            })
            log.info(f"  Added shareholder {cid} to {hub_empresa}")

    all_shareholders = existing_dirs + new_shareholders

    # Ensure the empresa has a REESTRUCTURADO loan
    empresa_loans = [p for p in prestamos if p["id_titular"] == hub_empresa]
    if empresa_loans:
        empresa_loans[0]["estatus"] = "REESTRUCTURADO"
        empresa_loans[0]["dias_mora"] = 15
        hub_loan = empresa_loans[0]["id_prestamo"]
        log.info(f"  Set {hub_loan} to REESTRUCTURADO")
    else:
        hub_loan_id = next_id("PRE-", prestamos, "id_prestamo")
        prestamos.append({
            "id_prestamo": hub_loan_id,
            "id_titular": hub_empresa,
            "tipo_titular": "EMPRESA",
            "monto_original_mxn": 5_500_000.00,
            "saldo_vigente_mxn": 4_800_000.00,
            "tasa_interes_anual": 0.12,
            "fecha_inicio": (date.today() - timedelta(days=600)).isoformat(),
            "fecha_vencimiento": (date.today() + timedelta(days=1200)).isoformat(),
            "estatus": "REESTRUCTURADO",
            "dias_mora": 15,
            "probabilidad_incumplimiento": "",
            "score_version": "",
            "score_fecha": "",
        })
        hub_loan = hub_loan_id
        log.info(f"  Created loan {hub_loan} for {hub_empresa}")

    # Each shareholder guarantees the empresa's loan
    for cid in all_shareholders:
        exists = any(
            g["id_garante"] == cid and g["id_prestamo"] == hub_loan
            for g in garantias
        )
        if not exists:
            new_id = next_id("GAR-", garantias, "id_garantia")
            garantias.append({
                "id_garantia": new_id,
                "id_prestamo": hub_loan,
                "id_garante": cid,
                "tipo_garantia": "AVAL",
                "cobertura_porcentaje": round(random.uniform(0.15, 0.40), 2),
                "fecha_inicio": (date.today() - timedelta(days=500)).isoformat(),
                "fecha_vencimiento": (date.today() + timedelta(days=1200)).isoformat(),
                "activa": True,
            })

    # Cross-guarantees: first 2 shareholders guarantee each other's personal loans
    cross_pair = all_shareholders[:2]
    for i, garante in enumerate(cross_pair):
        target = cross_pair[1 - i]
        target_loans = [p for p in prestamos if p["id_titular"] == target and p["estatus"] == "ACTIVO"]
        if not target_loans:
            new_id = next_id("PRE-", prestamos, "id_prestamo")
            prestamos.append({
                "id_prestamo": new_id,
                "id_titular": target,
                "tipo_titular": "INDIVIDUAL",
                "monto_original_mxn": round(float(np.random.lognormal(12.0, 0.8)), 2),
                "saldo_vigente_mxn": round(float(np.random.lognormal(11.5, 0.8)), 2),
                "tasa_interes_anual": round(random.uniform(0.10, 0.25), 4),
                "fecha_inicio": (date.today() - timedelta(days=300)).isoformat(),
                "fecha_vencimiento": (date.today() + timedelta(days=700)).isoformat(),
                "estatus": "ACTIVO",
                "dias_mora": 0,
                "probabilidad_incumplimiento": "",
                "score_version": "",
                "score_fecha": "",
            })
            target_loans = [prestamos[-1]]

        gar_id = next_id("GAR-", garantias, "id_garantia")
        garantias.append({
            "id_garantia": gar_id,
            "id_prestamo": target_loans[0]["id_prestamo"],
            "id_garante": garante,
            "tipo_garantia": "AVAL",
            "cobertura_porcentaje": 0.50,
            "fecha_inicio": (date.today() - timedelta(days=300)).isoformat(),
            "fecha_vencimiento": (date.today() + timedelta(days=700)).isoformat(),
            "activa": True,
        })
        log.info(f"  Cross-guarantee: {garante} -> {target}'s loan")

    scenario_info = {
        "name": "Corporate contagion hub",
        "hub_empresa": hub_empresa,
        "shareholders": all_shareholders,
        "hub_loan": hub_loan,
        "cross_guarantee_pair": cross_pair,
        "contagion_path": f"{hub_empresa} (REESTRUCTURADO) -> 5 shareholders exposed via guarantees -> 2 shareholders cross-exposed via personal loan guarantees",
        "cypher_query": "MATCH (e:Empresa {id_empresa:'EMP-00031'})<-[:GARANTIZA]-(c:ClienteIndividual)-[:GARANTIZA]->(p2:Prestamo) RETURN e, c, p2",
        "why_sql_cant": "Multi-hop traversal from empresa -> shareholders -> their other loans requires multiple JOINs with dynamic fan-out. SQL can't naturally express 'find all entities reachable within N hops of this node'.",
        "crisis_parallel": "Bear Stearns -- not the largest bank, but the most interconnected. Its failure cascaded through counterparty relationships. This empresa is a local version of that topology.",
    }
    return scenario_info


# ---------------------------------------------------------------------------
# Scenario 4: Shared director (partes relacionadas) -- uses REAL topology
# ---------------------------------------------------------------------------
def embed_scenario_4(clientes, empresas, prestamos, garantias, relaciones):
    """
    CLI-00194 (Judith Corral Gallegos) is a director of both EMP-00031
    and EMP-00041. This is REAL topology from UK PSC data, not synthetic.

    Ensure both companies have active loans so the concentration risk
    is visible in the graph.
    """
    log.info("Scenario 4: Shared director (partes relacionadas)")

    # Find the actual shared directors from the relaciones data
    from collections import Counter
    person_companies = {}
    for r in relaciones:
        person_companies.setdefault(r["id_individuo"], []).append(r["id_empresa"])

    shared_directors = {p: cs for p, cs in person_companies.items() if len(cs) >= 2}

    # Pick the most connected shared director
    best_director = max(shared_directors, key=lambda p: len(shared_directors[p]))
    director_companies = shared_directors[best_director]

    director_name = next(
        (c["nombre_completo"] for c in clientes if c["id_cliente"] == best_director),
        "?"
    )
    log.info(f"  Shared director: {best_director} ({director_name})")
    log.info(f"  Controls: {director_companies}")

    # Ensure each company has an active loan
    for emp_id in director_companies:
        emp_loans = [p for p in prestamos if p["id_titular"] == emp_id and p["estatus"] == "ACTIVO"]
        if not emp_loans:
            new_id = next_id("PRE-", prestamos, "id_prestamo")
            prestamos.append({
                "id_prestamo": new_id,
                "id_titular": emp_id,
                "tipo_titular": "EMPRESA",
                "monto_original_mxn": round(float(np.random.lognormal(14.0, 1.0)), 2),
                "saldo_vigente_mxn": round(float(np.random.lognormal(13.5, 1.0)), 2),
                "tasa_interes_anual": round(random.uniform(0.08, 0.20), 4),
                "fecha_inicio": (date.today() - timedelta(days=400)).isoformat(),
                "fecha_vencimiento": (date.today() + timedelta(days=1000)).isoformat(),
                "estatus": "ACTIVO",
                "dias_mora": 0,
                "probabilidad_incumplimiento": "",
                "score_version": "",
                "score_fecha": "",
            })
            log.info(f"  Created active loan for {emp_id}")

    # Get company names for documentation
    company_names = {}
    for emp_id in director_companies:
        name = next(
            (e["razon_social"][:40] for e in empresas if e["id_empresa"] == emp_id),
            "?"
        )
        company_names[emp_id] = name

    scenario_info = {
        "name": "Shared director (partes relacionadas)",
        "source": "REAL UK PSC topology (not synthetic)",
        "director": best_director,
        "director_name": director_name,
        "companies": {eid: company_names.get(eid, "?") for eid in director_companies},
        "cypher_query": f"MATCH (c:ClienteIndividual {{id_cliente:'{best_director}'}})-[:ES_ACCIONISTA_DE|ES_DIRECTOR_DE]->(e:Empresa)-[:TIENE_PRESTAMO]->(p:Prestamo) RETURN c, e, p",
        "why_sql_cant": "Finding shared directors requires self-joining a relationship table and checking for entity overlap. The graph pattern match is one line: (person)-[:DIRECTS]->(company1), (person)-[:DIRECTS]->(company2).",
        "crisis_parallel": "Dick Fuld was CEO of Lehman AND sat on the board of the NY Fed. Concentration of control creates correlated failure modes that entity-level analysis misses.",
        "regulation": "CNBV Circular Unica de Bancos Article 73 requires monitoring of personas relacionadas -- individuals with significant positions in multiple borrowing entities.",
    }
    return scenario_info


# ---------------------------------------------------------------------------
# Scenario 5: Unsecured high-PD active loans
# ---------------------------------------------------------------------------
def embed_scenario_5(clientes, empresas, prestamos, garantias):
    """
    15 active loans with no guarantor, high risk indicators:
    - estatus = ACTIVO
    - High tasa_interes (above 30% -- risk pricing signal)
    - score_buro of borrower below 500

    Demonstrates relationship ABSENCE query + property filter.
    """
    log.info("Scenario 5: Unsecured high-PD active loans")

    # Find active loans that have NO guarantee
    guaranteed_loans = {g["id_prestamo"] for g in garantias}
    active_unguaranteed = [
        p for p in prestamos
        if p["estatus"] == "ACTIVO" and p["id_prestamo"] not in guaranteed_loans
    ]
    log.info(f"  Active unguaranteed loans available: {len(active_unguaranteed)}")

    # Pick 15 (or create if not enough)
    target = 15
    selected = active_unguaranteed[:target]

    # Make them high-risk: high interest rate as risk pricing signal
    scenario_loans = []
    for loan in selected:
        loan["tasa_interes_anual"] = round(random.uniform(0.30, 0.45), 4)
        scenario_loans.append(loan["id_prestamo"])

        # Also lower the borrower's credit score
        borrower_id = loan["id_titular"]
        for c in clientes:
            if c["id_cliente"] == borrower_id:
                c["score_buro"] = round(random.uniform(300, 480), 1)
                break

    # If we don't have enough, create more
    while len(scenario_loans) < target:
        # Pick a random client with low score
        low_score_clients = [c for c in clientes if float(c["score_buro"]) < 500]
        if not low_score_clients:
            low_score_clients = clientes[-20:]

        client = random.choice(low_score_clients)
        new_id = next_id("PRE-", prestamos, "id_prestamo")
        prestamos.append({
            "id_prestamo": new_id,
            "id_titular": client["id_cliente"],
            "tipo_titular": "INDIVIDUAL",
            "monto_original_mxn": round(float(np.random.lognormal(11.5, 0.5)), 2),
            "saldo_vigente_mxn": round(float(np.random.lognormal(11.0, 0.5)), 2),
            "tasa_interes_anual": round(random.uniform(0.35, 0.45), 4),
            "fecha_inicio": (date.today() - timedelta(days=random.randint(60, 300))).isoformat(),
            "fecha_vencimiento": (date.today() + timedelta(days=random.randint(200, 800))).isoformat(),
            "estatus": "ACTIVO",
            "dias_mora": 0,
            "probabilidad_incumplimiento": "",
            "score_version": "",
            "score_fecha": "",
        })
        scenario_loans.append(new_id)
        log.info(f"  Created unsecured high-risk loan {new_id}")

    scenario_info = {
        "name": "Unsecured high-PD active loans",
        "loan_count": len(scenario_loans),
        "loans": scenario_loans,
        "risk_indicators": "tasa_interes > 30%, score_buro < 500, no guarantor",
        "cypher_query": "MATCH (c:ClienteIndividual)-[:TIENE_PRESTAMO]->(p:Prestamo {estatus:'ACTIVO'}) WHERE p.tasa_interes_anual > 0.30 AND NOT (p)<-[:GARANTIZA]-() RETURN c, p ORDER BY p.saldo_vigente_mxn DESC",
        "why_sql_cant": "The NOT EXISTS subquery for 'no guarantor' is possible in SQL but becomes expensive with multiple relationship absence conditions. In Cypher, `NOT (p)<-[:GARANTIZA]-()` is a native pattern negation.",
        "crisis_parallel": "Pre-2008 subprime lending -- high-risk loans without adequate collateral or guarantees, priced with high rates to compensate but still inadequately provisioned because the correlation of defaults was not modeled.",
    }
    return scenario_info


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info("=" * 60)
    log.info("Loading raw CSVs")
    log.info("=" * 60)

    clientes = load_csv("clientes_raw.csv")
    empresas = load_csv("empresas_raw.csv")
    prestamos = load_csv("prestamos_raw.csv")
    garantias = load_csv("garantias_raw.csv")
    relaciones = load_csv("relaciones_raw.csv")

    log.info(f"  Before: {len(prestamos)} loans, {len(garantias)} guarantees, {len(relaciones)} relations")

    manifest = {}

    # Embed scenarios
    log.info("\n" + "=" * 60)
    manifest["scenario_1"] = embed_scenario_1(clientes, empresas, prestamos, garantias)
    log.info("")
    manifest["scenario_2"] = embed_scenario_2(clientes, empresas, prestamos, garantias)
    log.info("")
    manifest["scenario_3"] = embed_scenario_3(clientes, empresas, prestamos, garantias, relaciones)
    log.info("")
    manifest["scenario_4"] = embed_scenario_4(clientes, empresas, prestamos, garantias, relaciones)
    log.info("")
    manifest["scenario_5"] = embed_scenario_5(clientes, empresas, prestamos, garantias)

    # Write modified CSVs
    log.info("\n" + "=" * 60)
    log.info("Writing modified CSVs")
    log.info("=" * 60)
    write_csv(clientes, "clientes_raw.csv")
    write_csv(empresas, "empresas_raw.csv")
    write_csv(prestamos, "prestamos_raw.csv")
    write_csv(garantias, "garantias_raw.csv")
    write_csv(relaciones, "relaciones_raw.csv")

    log.info(f"  After: {len(prestamos)} loans, {len(garantias)} guarantees, {len(relaciones)} relations")

    # Write scenario manifest
    manifest_path = SOURCE_DIR / "scenario_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    log.info(f"\n  Scenario manifest: {manifest_path}")

    log.info("\n" + "=" * 60)
    log.info("All 5 scenarios embedded.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
