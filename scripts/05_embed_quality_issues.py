"""
05_embed_quality_issues.py
--------------------------
Injects the exact data quality issues documented in creditgraph-spec.md.
These are real problems that bank data teams encounter weekly.

Each issue has a purpose:
  - Negative income: inverts the risk signal in ML models
  - Duplicate CURP: double-counts concentration risk
  - Orphaned FK: loan references a nonexistent borrower
  - Future birth date: data entry error
  - Minor (age 16): regulatory violation
  - saldo > monto: logical impossibility
  - dias_mora > 0 on ACTIVO: status inconsistency

The script modifies data/raw/*.csv IN PLACE.
Output: data/source/quality_issues_manifest.json documenting every issue.
"""

import csv
import json
import logging
import random
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
SOURCE_DIR = Path(__file__).resolve().parent.parent / "data" / "source"
SEED = 77
random.seed(SEED)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_csv(filename):
    with open(RAW_DIR / filename, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(data, filename):
    path = RAW_DIR / filename
    fieldnames = list(data[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    log.info(f"  Wrote {len(data)} rows to {path}")


def pick_indices(data, n, exclude=None):
    """Pick n random indices, avoiding scenario entities and already-picked."""
    exclude = exclude or set()
    available = [i for i in range(len(data)) if i not in exclude]
    return random.sample(available, min(n, len(available)))


# ---------------------------------------------------------------------------
# Clientes quality issues
# ---------------------------------------------------------------------------
def inject_clientes_issues(clientes):
    """
    From spec:
    - 5 duplicates: different id_cliente but same CURP
    - 8 nombre_completo = NULL
    - 3 nombre_completo = "N/A"
    - 4 CURP with invalid format (wrong length)
    - 2 fecha_nacimiento with future dates
    - 1 fecha_nacimiento for a minor (age 16)
    - 6 estado_residencia = NULL
    - Inconsistent naming: some "CDMX" vs "Ciudad de Mexico"
    - 3 nivel_ingresos with negative values
    - 12 nivel_ingresos = NULL
    - 7 score_buro outside valid range [300, 850]
    """
    issues = []
    used = set()

    # Protect scenario entities from corruption
    scenario_ids = {"CLI-00010", "CLI-00011", "CLI-00012",  # scenario 1
                    "CLI-00020", "CLI-00021", "CLI-00022",  # scenario 2
                    "CLI-00030", "CLI-00031", "CLI-00032",  # scenario 3
                    "CLI-00194", "CLI-00222", "CLI-00298"}  # scenarios 3+4
    protected = {i for i, c in enumerate(clientes) if c["id_cliente"] in scenario_ids}

    # 1. Duplicate CURPs (5 records share CURP with another record)
    # Credit risk impact: same person counted twice under different IDs.
    # The bank thinks exposure is spread across 2 clients. It's actually
    # concentrated in 1. Concentration risk is systematically understated.
    # This happens when a client re-registers after a system migration
    # and the dedup process fails on the CURP match.
    source_indices = pick_indices(clientes, 5, protected)
    for idx in source_indices:
        # Find another record to give the same CURP
        target_indices = pick_indices(clientes, 1, protected | used | set(source_indices))
        if target_indices:
            t = target_indices[0]
            original_curp = clientes[t]["curp"]
            clientes[t]["curp"] = clientes[idx]["curp"]
            used.add(t)
            issues.append({
                "entity": "clientes",
                "field": "curp",
                "type": "duplicate_curp",
                "record": clientes[t]["id_cliente"],
                "detail": f"Same CURP as {clientes[idx]['id_cliente']}",
            })
    log.info(f"  Duplicate CURPs: {len(source_indices)} injected")

    # 2. NULL nombre_completo (8 records)
    # Operational impact: can't verify identity, can't send collection notices.
    # Common when batch imports from a third-party system drop the name field.
    for idx in pick_indices(clientes, 8, protected | used):
        clientes[idx]["nombre_completo"] = ""
        used.add(idx)
        issues.append({
            "entity": "clientes", "field": "nombre_completo",
            "type": "null_name", "record": clientes[idx]["id_cliente"],
        })

    # 3. "N/A" nombre_completo (3 records)
    # Subtler than NULL: passes a `IS NOT NULL` check but isn't a real name.
    # ETL must check for placeholder strings, not just nulls.
    for idx in pick_indices(clientes, 3, protected | used):
        clientes[idx]["nombre_completo"] = "N/A"
        used.add(idx)
        issues.append({
            "entity": "clientes", "field": "nombre_completo",
            "type": "placeholder_name", "record": clientes[idx]["id_cliente"],
        })
    log.info(f"  NULL/N/A names: 11 injected")

    # 4. Invalid CURP format (4 records with wrong length)
    # A valid CURP is exactly 18 chars. A 15-char or 20-char CURP means
    # the data entry truncated or appended characters. Can't validate
    # identity against RENAPO, can't generate RFC from it.
    for idx in pick_indices(clientes, 4, protected | used):
        curp = clientes[idx]["curp"]
        if random.random() < 0.5:
            clientes[idx]["curp"] = curp[:15]
        else:
            clientes[idx]["curp"] = curp + "XX"
        used.add(idx)
        issues.append({
            "entity": "clientes", "field": "curp",
            "type": "invalid_curp_length",
            "record": clientes[idx]["id_cliente"],
            "detail": f"Length {len(clientes[idx]['curp'])} (should be 18)",
        })
    log.info(f"  Invalid CURP length: 4 injected")

    # 5. Future birth dates (2 records)
    # Data entry error: someone typed 2027 instead of 1997. The age
    # calculation goes negative, which breaks credit scoring features
    # like antiguedad_cliente and lifecycle stage classification.
    for idx in pick_indices(clientes, 2, protected | used):
        future_date = date.today() + timedelta(days=random.randint(30, 365))
        clientes[idx]["fecha_nacimiento"] = future_date.isoformat()
        used.add(idx)
        issues.append({
            "entity": "clientes", "field": "fecha_nacimiento",
            "type": "future_birthdate", "record": clientes[idx]["id_cliente"],
            "detail": str(future_date),
        })

    # 6. Minor (age 16) (1 record)
    # Not just a data error -- a regulatory violation. CNBV requires
    # borrowers to be of legal age. If this reaches production, the
    # institution faces audit findings. ETL must escalate, not just clean.
    for idx in pick_indices(clientes, 1, protected | used):
        minor_date = date.today() - timedelta(days=16 * 365 + random.randint(0, 180))
        clientes[idx]["fecha_nacimiento"] = minor_date.isoformat()
        used.add(idx)
        issues.append({
            "entity": "clientes", "field": "fecha_nacimiento",
            "type": "minor", "record": clientes[idx]["id_cliente"],
            "detail": f"Born {minor_date}, age ~16",
        })
    log.info(f"  Date issues: 3 injected (2 future, 1 minor)")

    # 7. NULL estado_residencia (6 records)
    # Breaks geographic concentration analysis and INEGI code mapping.
    for idx in pick_indices(clientes, 6, protected | used):
        clientes[idx]["estado_residencia"] = ""
        used.add(idx)
        issues.append({
            "entity": "clientes", "field": "estado_residencia",
            "type": "null_state", "record": clientes[idx]["id_cliente"],
        })

    # 8. Inconsistent state naming (change some "CDMX" to "Ciudad de Mexico")
    # Same state, different string. A GROUP BY on estado_residencia would
    # show "CDMX" and "Ciudad de Mexico" as two separate categories,
    # splitting the geographic concentration analysis.
    cdmx_indices = [i for i, c in enumerate(clientes)
                    if c["estado_residencia"] == "CDMX" and i not in protected]
    for idx in cdmx_indices[:5]:
        clientes[idx]["estado_residencia"] = "Ciudad de Mexico"
        issues.append({
            "entity": "clientes", "field": "estado_residencia",
            "type": "inconsistent_naming", "record": clientes[idx]["id_cliente"],
            "detail": "'Ciudad de Mexico' instead of 'CDMX'",
        })
    log.info(f"  State issues: 6 NULL + 5 inconsistent naming")

    # 9. Negative income (3 records)
    # Does not fail silently -- it INVERTS the risk signal. An ML model
    # sees -34000 as "very low income" but in the wrong direction. The
    # feature becomes anti-correlated with default. LightGBM will learn
    # a spurious split on negative income that appears to reduce PD.
    for idx in pick_indices(clientes, 3, protected | used):
        clientes[idx]["nivel_ingresos"] = str(-abs(float(clientes[idx]["nivel_ingresos"])))
        used.add(idx)
        issues.append({
            "entity": "clientes", "field": "nivel_ingresos",
            "type": "negative_income", "record": clientes[idx]["id_cliente"],
            "detail": clientes[idx]["nivel_ingresos"],
        })

    # 10. NULL income (12 records)
    # Missing income can't be imputed safely -- median imputation would
    # mask the real signal. Must be flagged and handled explicitly by
    # the scoring model (separate bin or exclusion from income features).
    for idx in pick_indices(clientes, 12, protected | used):
        clientes[idx]["nivel_ingresos"] = ""
        used.add(idx)
        issues.append({
            "entity": "clientes", "field": "nivel_ingresos",
            "type": "null_income", "record": clientes[idx]["id_cliente"],
        })
    log.info(f"  Income issues: 3 negative + 12 NULL")

    # 11. score_buro outside [300, 850] (7 records)
    # Credit bureau scores have a defined range. A score of 150 or 920
    # means the data came from a system that doesn't use the same scale,
    # or a format conversion error. Using it raw corrupts the PD model.
    for idx in pick_indices(clientes, 7, protected | used):
        if random.random() < 0.5:
            clientes[idx]["score_buro"] = str(round(random.uniform(100, 280), 1))
        else:
            clientes[idx]["score_buro"] = str(round(random.uniform(860, 999), 1))
        used.add(idx)
        issues.append({
            "entity": "clientes", "field": "score_buro",
            "type": "score_out_of_range", "record": clientes[idx]["id_cliente"],
            "detail": clientes[idx]["score_buro"],
        })
    log.info(f"  Score out of range: 7 injected")

    return issues


# ---------------------------------------------------------------------------
# Empresas quality issues
# ---------------------------------------------------------------------------
def inject_empresas_issues(empresas):
    """
    From spec:
    - 2 razon_social = NULL
    - 3 RFC with 13 characters (individual format, wrong for company)
    - 4 ingresos_anuales_mxn = NULL
    - 1 ingresos_anuales_mxn = 0
    - 3 num_empleados = NULL
    - 5 estado_registro inconsistent with INEGI codes
    """
    issues = []
    used = set()
    # Protect scenario 3 hub and GLEIF hierarchy empresas
    protected = set()
    for i, e in enumerate(empresas):
        if e["id_empresa"] in ("EMP-00031",):
            protected.add(i)

    # 1. NULL razon_social (2)
    # Can't identify the company. Breaks any reporting that groups by
    # company name, and makes the graph node uninterpretable visually.
    for idx in pick_indices(empresas, 2, protected | used):
        empresas[idx]["razon_social"] = ""
        used.add(idx)
        issues.append({"entity": "empresas", "field": "razon_social",
                       "type": "null_name", "record": empresas[idx]["id_empresa"]})

    # 2. 13-char RFC (3) -- individual format instead of company
    # Company RFCs are 12 chars. Individual RFCs are 13. If a company
    # has a 13-char RFC, either the company is misclassified (it's
    # actually a persona fisica con actividad empresarial) or someone
    # entered the representative's personal RFC by mistake.
    for idx in pick_indices(empresas, 3, protected | used):
        rfc = empresas[idx]["rfc"]
        empresas[idx]["rfc"] = rfc[:12] + random.choice("0123456789")
        used.add(idx)
        issues.append({"entity": "empresas", "field": "rfc",
                       "type": "individual_rfc_format", "record": empresas[idx]["id_empresa"],
                       "detail": f"Length {len(empresas[idx]['rfc'])} (should be 12)"})

    # 3. NULL ingresos (4) + zero (1)
    for idx in pick_indices(empresas, 4, protected | used):
        empresas[idx]["ingresos_anuales_mxn"] = ""
        used.add(idx)
        issues.append({"entity": "empresas", "field": "ingresos_anuales_mxn",
                       "type": "null_revenue", "record": empresas[idx]["id_empresa"]})
    for idx in pick_indices(empresas, 1, protected | used):
        empresas[idx]["ingresos_anuales_mxn"] = "0"
        used.add(idx)
        issues.append({"entity": "empresas", "field": "ingresos_anuales_mxn",
                       "type": "zero_revenue", "record": empresas[idx]["id_empresa"]})

    # 4. NULL num_empleados (3)
    for idx in pick_indices(empresas, 3, protected | used):
        empresas[idx]["num_empleados"] = ""
        used.add(idx)
        issues.append({"entity": "empresas", "field": "num_empleados",
                       "type": "null_employees", "record": empresas[idx]["id_empresa"]})

    # 5. Inconsistent state codes (5) -- use abbreviations instead of full names
    bad_states = {"CMX": "CDMX", "NL": "Nuevo Leon", "JAL": "Jal.",
                  "MEX": "Edo. Mex.", "QRO": "Qro"}
    state_indices = pick_indices(empresas, 5, protected | used)
    for i, idx in enumerate(state_indices):
        abbr = list(bad_states.keys())[i % len(bad_states)]
        empresas[idx]["estado_registro"] = abbr
        used.add(idx)
        issues.append({"entity": "empresas", "field": "estado_registro",
                       "type": "inconsistent_state_code", "record": empresas[idx]["id_empresa"],
                       "detail": f"'{abbr}' instead of standard name"})

    log.info(f"  Empresas: 2 null names, 3 bad RFCs, 5 null/zero revenue, 3 null employees, 5 bad states")
    return issues


# ---------------------------------------------------------------------------
# Prestamos quality issues
# ---------------------------------------------------------------------------
def inject_prestamos_issues(prestamos, clientes, empresas):
    """
    From spec:
    - 8 orphaned id_titular (borrower doesn't exist)
    - 3 tipo_titular inconsistent with actual id_titular type
    - 2 monto_original_mxn = NULL, 1 negative
    - 5 saldo_vigente > monto_original
    - 3 tasa_interes > 0.80 (usury flag)
    - 3 fecha_inicio > fecha_vencimiento
    - 4 dias_mora > 0 when estatus = ACTIVO
    """
    issues = []
    used = set()

    # Protect scenario loans
    scenario_titulars = {"CLI-00010", "CLI-00011", "CLI-00012",
                         "CLI-00020", "CLI-00021", "CLI-00022",
                         "EMP-00031"}
    protected = {i for i, p in enumerate(prestamos) if p["id_titular"] in scenario_titulars}

    valid_client_ids = {c["id_cliente"] for c in clientes}
    valid_empresa_ids = {e["id_empresa"] for e in empresas}

    # 1. Orphaned id_titular (8)
    # The loan references a borrower that doesn't exist in the client table.
    # Happens when a client is deleted but their loans aren't cascaded.
    # Risk: can't assess the borrower's creditworthiness, can't compute
    # concentration by client, can't trace the guarantee chain from this loan.
    for idx in pick_indices(prestamos, 8, protected | used):
        prestamos[idx]["id_titular"] = f"CLI-99{random.randint(1,9):03d}"
        used.add(idx)
        issues.append({"entity": "prestamos", "field": "id_titular",
                       "type": "orphaned_fk", "record": prestamos[idx]["id_prestamo"],
                       "detail": f"References {prestamos[idx]['id_titular']} which does not exist"})

    # 2. Inconsistent tipo_titular (3) -- says INDIVIDUAL but id is EMP, or vice versa
    # The tipo says EMPRESA but the id_titular starts with CLI-. Which is
    # correct? You can't tell without looking at the source system. This
    # breaks the loan distribution split (70% individual / 30% corporate)
    # and misroutes the loan to the wrong scoring model.
    individual_loans = [i for i, p in enumerate(prestamos)
                        if p["tipo_titular"] == "INDIVIDUAL"
                        and p["id_titular"].startswith("CLI-")
                        and i not in protected | used]
    for idx in individual_loans[:3]:
        prestamos[idx]["tipo_titular"] = "EMPRESA"
        used.add(idx)
        issues.append({"entity": "prestamos", "field": "tipo_titular",
                       "type": "type_mismatch", "record": prestamos[idx]["id_prestamo"],
                       "detail": f"tipo=EMPRESA but id_titular={prestamos[idx]['id_titular']} is a client"})

    # 3. NULL monto (2) + negative (1)
    for idx in pick_indices(prestamos, 2, protected | used):
        prestamos[idx]["monto_original_mxn"] = ""
        used.add(idx)
        issues.append({"entity": "prestamos", "field": "monto_original_mxn",
                       "type": "null_amount", "record": prestamos[idx]["id_prestamo"]})
    for idx in pick_indices(prestamos, 1, protected | used):
        prestamos[idx]["monto_original_mxn"] = str(-abs(float(prestamos[idx]["monto_original_mxn"])))
        used.add(idx)
        issues.append({"entity": "prestamos", "field": "monto_original_mxn",
                       "type": "negative_amount", "record": prestamos[idx]["id_prestamo"]})

    # 4. saldo > monto (5)
    # You can't owe more than you borrowed (excluding capitalized interest,
    # which this schema doesn't model). saldo_vigente IS the EAD
    # (exposure at default) for first-order analysis. If it's wrong,
    # the entire contagion calculation through guarantee chains is wrong.
    candidates = [i for i, p in enumerate(prestamos)
                  if p["monto_original_mxn"] and p["saldo_vigente_mxn"]
                  and i not in protected | used]
    for idx in random.sample(candidates, min(5, len(candidates))):
        monto = float(prestamos[idx]["monto_original_mxn"])
        prestamos[idx]["saldo_vigente_mxn"] = str(round(monto * random.uniform(1.1, 1.5), 2))
        used.add(idx)
        issues.append({"entity": "prestamos", "field": "saldo_vigente_mxn",
                       "type": "saldo_exceeds_monto", "record": prestamos[idx]["id_prestamo"],
                       "detail": f"Saldo {prestamos[idx]['saldo_vigente_mxn']} > Monto {monto}"})

    # 5. Usury interest rate > 80% (3)
    # Rates above ~45% are already aggressive for MX consumer lending.
    # Above 80% signals a data conversion error (monthly rate stored as
    # annual, or a decimal place shifted). Could also flag an actual
    # usury violation under Ley Federal de Proteccion al Consumidor.
    for idx in pick_indices(prestamos, 3, protected | used):
        prestamos[idx]["tasa_interes_anual"] = str(round(random.uniform(0.82, 0.99), 4))
        used.add(idx)
        issues.append({"entity": "prestamos", "field": "tasa_interes_anual",
                       "type": "usury_rate", "record": prestamos[idx]["id_prestamo"],
                       "detail": prestamos[idx]["tasa_interes_anual"]})

    # 6. fecha_inicio > fecha_vencimiento (3)
    # Loan starts after it ends -- logically impossible. Swapped columns
    # during a data migration. The plazo (term) calculation goes negative,
    # breaking any feature that uses loan tenure or remaining term.
    for idx in pick_indices(prestamos, 3, protected | used):
        inicio = prestamos[idx]["fecha_inicio"]
        vencimiento = prestamos[idx]["fecha_vencimiento"]
        prestamos[idx]["fecha_inicio"] = vencimiento
        prestamos[idx]["fecha_vencimiento"] = inicio
        used.add(idx)
        issues.append({"entity": "prestamos", "field": "fecha_inicio",
                       "type": "start_after_end", "record": prestamos[idx]["id_prestamo"]})

    # 7. dias_mora > 0 on ACTIVO (4)
    # Status says current but the loan is past due. Either the status
    # wasn't updated (batch job lag) or dias_mora was computed from a
    # stale snapshot. Either way, the loan should be VENCIDO. This
    # understates the NPL ratio and masks the true portfolio quality.
    activo_indices = [i for i, p in enumerate(prestamos)
                      if p["estatus"] == "ACTIVO" and i not in protected | used]
    for idx in random.sample(activo_indices, min(4, len(activo_indices))):
        prestamos[idx]["dias_mora"] = str(random.randint(5, 25))
        used.add(idx)
        issues.append({"entity": "prestamos", "field": "dias_mora",
                       "type": "mora_on_activo", "record": prestamos[idx]["id_prestamo"],
                       "detail": f"dias_mora={prestamos[idx]['dias_mora']} but estatus=ACTIVO"})

    log.info(f"  Prestamos: 8 orphaned FK, 3 type mismatch, 3 bad amounts, 5 saldo>monto, 3 usury, 3 date swap, 4 mora on ACTIVO")
    return issues


# ---------------------------------------------------------------------------
# Garantias quality issues
# ---------------------------------------------------------------------------
def inject_garantias_issues(garantias, prestamos, clientes):
    """
    From spec:
    - 5 orphaned id_prestamo (loan doesn't exist)
    - 3 orphaned id_garante (guarantor doesn't exist)
    - 4 fecha_vencimiento already expired but loan still active
    - 6 activa inconsistent with fechas
    """
    issues = []
    used = set()

    # Protect scenario guarantees (GAR-00181 through GAR-00190 are scenario-embedded)
    protected = set()
    for i, g in enumerate(garantias):
        num = int(g["id_garantia"].split("-")[1])
        if num >= 181:
            protected.add(i)

    # 1. Orphaned id_prestamo (5)
    # Guarantee references a loan that doesn't exist. The guarantee is
    # floating in the graph with no anchor. Contagion analysis would
    # traverse this edge and find nothing on the other side.
    for idx in pick_indices(garantias, 5, protected | used):
        garantias[idx]["id_prestamo"] = f"PRE-99{random.randint(1,9):03d}"
        used.add(idx)
        issues.append({"entity": "garantias", "field": "id_prestamo",
                       "type": "orphaned_loan_fk", "record": garantias[idx]["id_garantia"],
                       "detail": f"References {garantias[idx]['id_prestamo']} which does not exist"})

    # 2. Orphaned id_garante (3)
    # Guarantor doesn't exist. The loan appears guaranteed (coverage > 0)
    # but the guarantor is a ghost. The real coverage is zero. This
    # overstates the loan's protection and understates true exposure.
    for idx in pick_indices(garantias, 3, protected | used):
        garantias[idx]["id_garante"] = f"CLI-99{random.randint(1,9):03d}"
        used.add(idx)
        issues.append({"entity": "garantias", "field": "id_garante",
                       "type": "orphaned_guarantor_fk", "record": garantias[idx]["id_garantia"],
                       "detail": f"References {garantias[idx]['id_garante']} which does not exist"})

    # 3. Expired guarantee but loan still active (4)
    # The guarantee expired 3 months ago but the loan still has 2 years
    # left. The contagion model thinks this loan is covered. It isn't.
    # Common when guarantee renewal is a manual process and nobody
    # triggers the update in the core banking system.
    for idx in pick_indices(garantias, 4, protected | used):
        expired_date = (date.today() - timedelta(days=random.randint(30, 365))).isoformat()
        garantias[idx]["fecha_vencimiento"] = expired_date
        garantias[idx]["activa"] = "True"  # inconsistent: expired but marked active
        used.add(idx)
        issues.append({"entity": "garantias", "field": "fecha_vencimiento",
                       "type": "expired_but_active_loan", "record": garantias[idx]["id_garantia"],
                       "detail": f"Expired {expired_date} but loan may still be active"})

    # 4. activa inconsistent with fechas (6)
    # Flag says inactive but the dates say it should still be valid.
    # Which is the source of truth -- the boolean or the dates?
    # ETL must pick one (dates are more reliable in practice) and
    # write a rejection_reason explaining the discrepancy.
    for idx in pick_indices(garantias, 6, protected | used):
        garantias[idx]["activa"] = "False"
        garantias[idx]["fecha_vencimiento"] = (date.today() + timedelta(days=500)).isoformat()
        used.add(idx)
        issues.append({"entity": "garantias", "field": "activa",
                       "type": "status_date_mismatch", "record": garantias[idx]["id_garantia"],
                       "detail": "activa=False but fecha_vencimiento is in the future"})

    log.info(f"  Garantias: 5 orphaned loans, 3 orphaned guarantors, 4 expired, 6 status mismatch")
    return issues


# ---------------------------------------------------------------------------
# Relaciones quality issues
# ---------------------------------------------------------------------------
def inject_relaciones_issues(relaciones, clientes, empresas):
    """
    From spec:
    - 4 orphaned id_individuo
    - 2 orphaned id_empresa
    """
    issues = []
    used = set()

    # Protect scenario relaciones
    scenario_entities = {"CLI-00194", "CLI-00222", "CLI-00298",
                         "EMP-00031", "EMP-00076", "EMP-00071"}
    protected = {i for i, r in enumerate(relaciones)
                 if r["id_individuo"] in scenario_entities or r["id_empresa"] in scenario_entities}

    # Also protect SUBSIDIARIA type (GLEIF hierarchy)
    for i, r in enumerate(relaciones):
        if r["tipo_relacion"] == "SUBSIDIARIA":
            protected.add(i)

    # 1. Orphaned id_individuo (4)
    # A relationship edge points to a person that doesn't exist.
    # The shared-director detection would miss this connection entirely,
    # and the contagion analysis would have a broken path.
    for idx in pick_indices(relaciones, 4, protected | used):
        relaciones[idx]["id_individuo"] = f"CLI-99{random.randint(1,9):03d}"
        used.add(idx)
        issues.append({"entity": "relaciones", "field": "id_individuo",
                       "type": "orphaned_person_fk", "record": relaciones[idx]["id_relacion"],
                       "detail": f"References {relaciones[idx]['id_individuo']}"})

    # 2. Orphaned id_empresa (2)
    # Relationship points to a company that doesn't exist. Same as above
    # but on the company side -- the ownership edge is dangling.
    for idx in pick_indices(relaciones, 2, protected | used):
        relaciones[idx]["id_empresa"] = f"EMP-99{random.randint(1,9):03d}"
        used.add(idx)
        issues.append({"entity": "relaciones", "field": "id_empresa",
                       "type": "orphaned_company_fk", "record": relaciones[idx]["id_relacion"],
                       "detail": f"References {relaciones[idx]['id_empresa']}"})

    log.info(f"  Relaciones: 4 orphaned persons, 2 orphaned companies")
    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info("=" * 60)
    log.info("Embedding data quality issues")
    log.info("=" * 60)

    clientes = load_csv("clientes_raw.csv")
    empresas = load_csv("empresas_raw.csv")
    prestamos = load_csv("prestamos_raw.csv")
    garantias = load_csv("garantias_raw.csv")
    relaciones = load_csv("relaciones_raw.csv")

    all_issues = []

    log.info("\nClientes:")
    all_issues.extend(inject_clientes_issues(clientes))

    log.info("\nEmpresas:")
    all_issues.extend(inject_empresas_issues(empresas))

    log.info("\nPrestamos:")
    all_issues.extend(inject_prestamos_issues(prestamos, clientes, empresas))

    log.info("\nGarantias:")
    all_issues.extend(inject_garantias_issues(garantias, prestamos, clientes))

    log.info("\nRelaciones:")
    all_issues.extend(inject_relaciones_issues(relaciones, clientes, empresas))

    # Write modified CSVs
    log.info("\n" + "=" * 60)
    log.info("Writing modified CSVs")
    log.info("=" * 60)
    write_csv(clientes, "clientes_raw.csv")
    write_csv(empresas, "empresas_raw.csv")
    write_csv(prestamos, "prestamos_raw.csv")
    write_csv(garantias, "garantias_raw.csv")
    write_csv(relaciones, "relaciones_raw.csv")

    # Write manifest
    manifest = {
        "total_issues": len(all_issues),
        "by_entity": {},
        "by_type": {},
        "issues": all_issues,
    }
    for issue in all_issues:
        entity = issue["entity"]
        itype = issue["type"]
        manifest["by_entity"][entity] = manifest["by_entity"].get(entity, 0) + 1
        manifest["by_type"][itype] = manifest["by_type"].get(itype, 0) + 1

    manifest_path = SOURCE_DIR / "quality_issues_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    log.info(f"\n  Total issues embedded: {len(all_issues)}")
    log.info(f"  By entity:")
    for entity, count in sorted(manifest["by_entity"].items()):
        log.info(f"    {entity}: {count}")
    log.info(f"  Manifest: {manifest_path}")
    log.info("\n" + "=" * 60)
    log.info("Done.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
