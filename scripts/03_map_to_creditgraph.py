"""
03_map_to_creditgraph.py
------------------------
Maps the extracted subgraph to the CreditGraph schema:
  1. UK PSC persons --> ClienteIndividual (Mexican identity)
  2. Selected companies --> Empresa (Mexican attributes)
  3. Generate 450 Prestamo records (loans)
  4. Generate 180 Garantia records (guarantees following topology)
  5. Map control edges --> Relaciones Empresariales

Output: 5 CSV files in data/raw/ (pre-quality-issues, pre-ETL)
  - clientes_raw.csv
  - empresas_raw.csv
  - prestamos_raw.csv
  - garantias_raw.csv
  - relaciones_raw.csv
"""

import csv
import json
import logging
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from faker import Faker

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SOURCE_DIR = Path(__file__).resolve().parent.parent / "data" / "source"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

TARGET_EMPRESAS = 80
TARGET_PRESTAMOS = 450
TARGET_GARANTIAS = 180
NPL_RATIO = 0.04  # ~4% default rate (Mexican conservative lender benchmark)

SEED = 42
random.seed(SEED)
np.random.seed(SEED)

fake = Faker("es_MX")
Faker.seed(SEED)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Mexican states with approximate population weights
MX_STATES = [
    ("CDMX", 0.20), ("Estado de Mexico", 0.14), ("Nuevo Leon", 0.10),
    ("Jalisco", 0.10), ("Puebla", 0.06), ("Guanajuato", 0.05),
    ("Chihuahua", 0.04), ("Queretaro", 0.04), ("Baja California", 0.04),
    ("Coahuila", 0.03), ("Sonora", 0.03), ("Veracruz", 0.03),
    ("Tamaulipas", 0.03), ("Yucatan", 0.02), ("San Luis Potosi", 0.02),
    ("Michoacan", 0.02), ("Sinaloa", 0.02), ("Aguascalientes", 0.02),
    ("Quintana Roo", 0.01),
]
MX_STATE_NAMES = [s[0] for s in MX_STATES]
MX_STATE_WEIGHTS = [s[1] for s in MX_STATES]

SECTORS = ["MANUFACTURA", "COMERCIO", "SERVICIOS", "CONSTRUCCION", "AGRO"]
SECTOR_WEIGHTS = [0.25, 0.30, 0.25, 0.15, 0.05]

SIZES = ["MICRO", "PEQUENA", "MEDIANA", "GRANDE"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_json(filename: str) -> list | dict:
    with open(SOURCE_DIR / filename) as f:
        return json.load(f)


def strip_accents(s: str) -> str:
    """Remove accents and diacritics, keeping ASCII only."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def generate_curp(name: str, birth_date: date, gender: str, state: str) -> str:
    """Generate a structurally valid 18-character Mexican CURP."""
    # Strip accents -- real CURPs are ASCII only
    name = strip_accents(name)
    # Split name into parts
    parts = name.upper().split()
    # Need at least paterno, materno, nombre
    if len(parts) >= 3:
        paterno, materno, nombre = parts[0], parts[1], parts[2]
    elif len(parts) == 2:
        paterno, materno, nombre = parts[0], "X", parts[1]
    else:
        paterno, materno, nombre = parts[0], "X", "X"

    # Positions 1-4: first letter paterno + first vowel paterno + first letter materno + first letter nombre
    def first_vowel(s):
        for c in s[1:]:
            if c in "AEIOU":
                return c
        return "X"

    pos1_4 = paterno[0] + first_vowel(paterno) + materno[0] + nombre[0]

    # Positions 5-10: YYMMDD
    pos5_10 = birth_date.strftime("%y%m%d")

    # Position 11: gender
    pos11 = "H" if gender == "M" else "M"

    # Positions 12-13: state code
    state_codes = {
        "CDMX": "DF", "Estado de Mexico": "MC", "Nuevo Leon": "NL",
        "Jalisco": "JC", "Puebla": "PL", "Guanajuato": "GT",
        "Chihuahua": "CH", "Queretaro": "QT", "Baja California": "BC",
        "Coahuila": "CL", "Sonora": "SR", "Veracruz": "VZ",
        "Tamaulipas": "TS", "Yucatan": "YN", "San Luis Potosi": "SP",
        "Michoacan": "MN", "Sinaloa": "SL", "Aguascalientes": "AS",
        "Quintana Roo": "QR",
    }
    pos12_13 = state_codes.get(state, "DF")

    # Positions 14-16: first internal consonant of each name part
    def first_consonant(s):
        for c in s[1:]:
            if c not in "AEIOU" and c.isalpha():
                return c
        return "X"

    pos14_16 = first_consonant(paterno) + first_consonant(materno) + first_consonant(nombre)

    # Position 17: disambiguator
    pos17 = random.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")

    # Position 18: check digit (simplified)
    pos18 = str(random.randint(0, 9))

    return pos1_4 + pos5_10 + pos11 + pos12_13 + pos14_16 + pos17 + pos18


def generate_rfc_empresa(name: str, incorp_date: date) -> str:
    """Generate a 12-character company RFC."""
    words = [w for w in name.upper().split() if w not in ("SA", "DE", "CV", "SAPI", "SAB")]
    # Positions 1-3: first letters of first 3 words
    pos1_3 = ""
    for w in words[:3]:
        if w:
            pos1_3 += w[0]
    pos1_3 = pos1_3.ljust(3, "X")[:3]

    # Positions 4-9: YYMMDD of incorporation
    pos4_9 = incorp_date.strftime("%y%m%d")

    # Positions 10-12: homoclave
    pos10_12 = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=3))

    return pos1_3 + pos4_9 + pos10_12


def pick_state() -> str:
    return random.choices(MX_STATE_NAMES, weights=MX_STATE_WEIGHTS, k=1)[0]


# ---------------------------------------------------------------------------
# Step 1: Generate ClienteIndividual
# ---------------------------------------------------------------------------
def generate_clientes(persons: list[dict]) -> list[dict]:
    """Map UK PSC persons to Mexican ClienteIndividual records."""
    clientes = []

    for i, person in enumerate(persons):
        cliente_id = f"CLI-{i+1:05d}"

        # Generate Mexican name
        gender = random.choice(["M", "F"])
        if gender == "M":
            nombre = fake.first_name_male() + " " + fake.last_name() + " " + fake.last_name()
        else:
            nombre = fake.first_name_female() + " " + fake.last_name() + " " + fake.last_name()

        # Birth date: keep real month/year from PSC, synthesize day
        birthdate_str = person.get("birthdate", "")
        if birthdate_str and len(birthdate_str) >= 7:
            try:
                year = int(birthdate_str[:4])
                month = int(birthdate_str[5:7])
                day = random.randint(1, 28)
                fecha_nac = date(year, month, day)
            except (ValueError, IndexError):
                fecha_nac = fake.date_of_birth(minimum_age=25, maximum_age=70)
        else:
            fecha_nac = fake.date_of_birth(minimum_age=25, maximum_age=70)

        estado = pick_state()

        # Income: lognormal, median ~25,000 MXN/month
        nivel_ingresos = round(float(np.random.lognormal(mean=10.1, sigma=0.7)), 2)

        # Credit score: normal(650, 80) clipped to [300, 850]
        score_buro = round(float(np.clip(np.random.normal(650, 80), 300, 850)), 1)

        # Client tenure: uniform 1-240 months
        antiguedad = random.randint(1, 240)

        # Default history: Poisson(0.3) clipped to [0, 5]
        historico = min(int(np.random.poisson(0.3)), 5)

        # Last default date (only if historico > 0)
        if historico > 0:
            days_ago = random.randint(180, 2000)
            fecha_ultimo = (date.today() - timedelta(days=days_ago)).isoformat()
        else:
            fecha_ultimo = ""

        curp = generate_curp(nombre, fecha_nac, gender, estado)

        clientes.append({
            "id_cliente": cliente_id,
            "nombre_completo": nombre,
            "curp": curp,
            "fecha_nacimiento": fecha_nac.isoformat(),
            "estado_residencia": estado,
            "nivel_ingresos": nivel_ingresos,
            "antiguedad_cliente_meses": antiguedad,
            "score_buro": score_buro,
            "historico_incumplimientos": historico,
            "fecha_ultimo_incumplimiento": fecha_ultimo,
            # Metadata for linking
            "_psc_person_id": person["person_id"],
            "_psc_fullname": person["fullname"],
        })

    return clientes


# ---------------------------------------------------------------------------
# Step 2: Generate Empresas
# ---------------------------------------------------------------------------
def generate_empresas(
    companies: list[dict],
    gleif_entities: list[dict],
    target: int,
) -> list[dict]:
    """Select ~80 companies and assign Mexican attributes."""

    # Use GLEIF MX company names as a name pool
    gleif_names = [
        e["legal_name"] for e in gleif_entities
        if e["legal_name"] and len(e["legal_name"]) > 5
    ]
    random.shuffle(gleif_names)
    name_pool = iter(gleif_names)

    # Select the most connected companies first
    selected = companies[:target]

    empresas = []
    for i, comp in enumerate(selected):
        empresa_id = f"EMP-{i+1:05d}"

        # Try to use a real GLEIF MX company name
        try:
            razon_social = next(name_pool)
        except StopIteration:
            razon_social = fake.company()

        # Sector
        sector = random.choices(SECTORS, weights=SECTOR_WEIGHTS, k=1)[0]

        # Size based on sector-influenced employee count
        num_empleados = int(np.random.lognormal(mean=3.5, sigma=1.2))
        if num_empleados <= 10:
            tamano = "MICRO"
        elif num_empleados <= 50:
            tamano = "PEQUENA"
        elif num_empleados <= 250:
            tamano = "MEDIANA"
        else:
            tamano = "GRANDE"

        # Revenue correlated with size
        revenue_multipliers = {"MICRO": 0.5, "PEQUENA": 2.0, "MEDIANA": 8.0, "GRANDE": 30.0}
        base_revenue = revenue_multipliers[tamano] * 1_000_000
        ingresos = round(float(base_revenue * np.random.lognormal(0, 0.5)), 2)

        # Years in operation
        anos = random.randint(1, 40)

        # Incorporation date (for RFC)
        incorp_date = date.today() - timedelta(days=anos * 365 + random.randint(0, 365))

        rfc = generate_rfc_empresa(razon_social, incorp_date)
        estado = pick_state()

        empresas.append({
            "id_empresa": empresa_id,
            "razon_social": razon_social,
            "rfc": rfc,
            "sector": sector,
            "tamano": tamano,
            "ingresos_anuales_mxn": ingresos,
            "anos_operacion": anos,
            "num_empleados": num_empleados,
            "estado_registro": estado,
            # Metadata for linking
            "_psc_company_ref": comp["company_ref"],
        })

    return empresas


# ---------------------------------------------------------------------------
# Step 3: Generate Prestamos
# ---------------------------------------------------------------------------
def generate_prestamos(
    clientes: list[dict],
    empresas: list[dict],
    target: int,
) -> list[dict]:
    """Generate loan records attached to clients and companies."""

    # 70% individual, 30% corporate
    n_individual = int(target * 0.70)
    n_corporate = target - n_individual

    prestamos = []
    prestamo_counter = 0

    # Individual loans
    # Some clients get 2 loans, most get 1
    client_ids = [c["id_cliente"] for c in clientes]
    random.shuffle(client_ids)

    assigned = 0
    idx = 0
    while assigned < n_individual:
        titular_id = client_ids[idx % len(client_ids)]
        prestamo_counter += 1
        prestamo_id = f"PRE-{prestamo_counter:05d}"

        # Amount: lognormal, median ~MXN 160K
        monto = round(float(np.random.lognormal(mean=12.0, sigma=0.8)), 2)

        # Status distribution: 72% ACTIVO, 15% PAGADO, 8% VENCIDO, 5% REESTRUCTURADO
        r = random.random()
        if r < 0.72:
            estatus = "ACTIVO"
        elif r < 0.87:
            estatus = "PAGADO"
        elif r < 0.95:
            estatus = "VENCIDO"
        else:
            estatus = "REESTRUCTURADO"

        # Outstanding balance
        if estatus == "PAGADO":
            saldo = 0.0
        elif estatus == "VENCIDO":
            saldo = round(monto * random.uniform(0.3, 1.0), 2)
        else:
            saldo = round(monto * random.uniform(0.1, 0.95), 2)

        # Interest rate
        tasa = round(random.uniform(0.05, 0.45), 4)

        # Dates
        dias_antiguedad = random.randint(30, 1800)
        fecha_inicio = date.today() - timedelta(days=dias_antiguedad)
        plazo_dias = random.choice([365, 730, 1095, 1460, 1825])
        fecha_vencimiento = fecha_inicio + timedelta(days=plazo_dias)

        # Days past due
        if estatus == "VENCIDO":
            dias_mora = random.randint(31, 180)
        elif estatus == "REESTRUCTURADO":
            dias_mora = random.randint(0, 30)
        else:
            dias_mora = 0

        prestamos.append({
            "id_prestamo": prestamo_id,
            "id_titular": titular_id,
            "tipo_titular": "INDIVIDUAL",
            "monto_original_mxn": monto,
            "saldo_vigente_mxn": saldo,
            "tasa_interes_anual": tasa,
            "fecha_inicio": fecha_inicio.isoformat(),
            "fecha_vencimiento": fecha_vencimiento.isoformat(),
            "estatus": estatus,
            "dias_mora": dias_mora,
            "probabilidad_incumplimiento": "",  # filled in Phase 3 (ML)
            "score_version": "",
            "score_fecha": "",
        })

        assigned += 1
        idx += 1

    # Corporate loans
    empresa_ids = [e["id_empresa"] for e in empresas]
    random.shuffle(empresa_ids)

    assigned = 0
    idx = 0
    while assigned < n_corporate:
        titular_id = empresa_ids[idx % len(empresa_ids)]
        prestamo_counter += 1
        prestamo_id = f"PRE-{prestamo_counter:05d}"

        # Corporate amounts: lognormal, median ~MXN 1.2M
        monto = round(float(np.random.lognormal(mean=14.0, sigma=1.0)), 2)

        r = random.random()
        if r < 0.72:
            estatus = "ACTIVO"
        elif r < 0.87:
            estatus = "PAGADO"
        elif r < 0.95:
            estatus = "VENCIDO"
        else:
            estatus = "REESTRUCTURADO"

        if estatus == "PAGADO":
            saldo = 0.0
        elif estatus == "VENCIDO":
            saldo = round(monto * random.uniform(0.3, 1.0), 2)
        else:
            saldo = round(monto * random.uniform(0.1, 0.95), 2)

        tasa = round(random.uniform(0.05, 0.35), 4)

        dias_antiguedad = random.randint(30, 1800)
        fecha_inicio = date.today() - timedelta(days=dias_antiguedad)
        plazo_dias = random.choice([365, 730, 1095, 1460, 1825, 2555, 3650])
        fecha_vencimiento = fecha_inicio + timedelta(days=plazo_dias)

        if estatus == "VENCIDO":
            dias_mora = random.randint(31, 180)
        elif estatus == "REESTRUCTURADO":
            dias_mora = random.randint(0, 30)
        else:
            dias_mora = 0

        prestamos.append({
            "id_prestamo": prestamo_id,
            "id_titular": titular_id,
            "tipo_titular": "EMPRESA",
            "monto_original_mxn": monto,
            "saldo_vigente_mxn": saldo,
            "tasa_interes_anual": tasa,
            "fecha_inicio": fecha_inicio.isoformat(),
            "fecha_vencimiento": fecha_vencimiento.isoformat(),
            "estatus": estatus,
            "dias_mora": dias_mora,
            "probabilidad_incumplimiento": "",
            "score_version": "",
            "score_fecha": "",
        })

        assigned += 1
        idx += 1

    random.shuffle(prestamos)
    return prestamos


# ---------------------------------------------------------------------------
# Step 4: Generate Garantias (following ownership topology)
# ---------------------------------------------------------------------------
def generate_garantias(
    clientes: list[dict],
    empresas: list[dict],
    prestamos: list[dict],
    psc_rels: list[dict],
    target: int,
) -> list[dict]:
    """Generate guarantee edges following the ownership topology."""

    # Build lookup maps
    psc_to_cliente = {}
    for c in clientes:
        psc_to_cliente[c["_psc_person_id"]] = c["id_cliente"]

    psc_to_empresa = {}
    for e in empresas:
        psc_to_empresa[e["_psc_company_ref"]] = e["id_empresa"]

    # Loans by titular
    loans_by_titular = {}
    for p in prestamos:
        loans_by_titular.setdefault(p["id_titular"], []).append(p)

    # PSC control edges mapped to CreditGraph IDs
    control_edges = []
    for rel in psc_rels:
        if rel["rel_type"] != "CONTROLS":
            continue
        cliente_id = psc_to_cliente.get(rel["from_id"])
        empresa_id = psc_to_empresa.get(rel["to_id"])
        if cliente_id and empresa_id:
            control_edges.append((cliente_id, empresa_id))

    garantias = []
    garantia_counter = 0
    tipos = ["PERSONAL", "HIPOTECARIA", "PRENDARIA", "AVAL"]

    # Rule 1: Shareholder guarantees their company's loans (p=0.7)
    for cliente_id, empresa_id in control_edges:
        if random.random() > 0.7:
            continue
        empresa_loans = loans_by_titular.get(empresa_id, [])
        active_loans = [l for l in empresa_loans if l["estatus"] in ("ACTIVO", "REESTRUCTURADO")]
        if not active_loans:
            continue

        loan = random.choice(active_loans)
        garantia_counter += 1
        cobertura = round(random.uniform(0.25, 1.0), 2)

        fecha_inicio = loan["fecha_inicio"]
        fecha_venc = loan["fecha_vencimiento"]

        garantias.append({
            "id_garantia": f"GAR-{garantia_counter:05d}",
            "id_prestamo": loan["id_prestamo"],
            "id_garante": cliente_id,
            "tipo_garantia": random.choice(tipos),
            "cobertura_porcentaje": cobertura,
            "fecha_inicio": fecha_inicio,
            "fecha_vencimiento": fecha_venc,
            "activa": True,
        })

    # Rule 2: Co-shareholders cross-guarantee personal loans (p=0.15)
    # Find pairs of clients who control the same company
    empresa_controllers = {}
    for cliente_id, empresa_id in control_edges:
        empresa_controllers.setdefault(empresa_id, []).append(cliente_id)

    for empresa_id, controllers in empresa_controllers.items():
        if len(controllers) < 2:
            continue
        for i in range(len(controllers)):
            for j in range(i + 1, len(controllers)):
                if random.random() > 0.5:
                    continue
                # Controller i guarantees controller j's personal loan
                target_loans = loans_by_titular.get(controllers[j], [])
                active_loans = [l for l in target_loans if l["estatus"] in ("ACTIVO", "REESTRUCTURADO")]
                if not active_loans:
                    continue

                loan = random.choice(active_loans)
                garantia_counter += 1
                garantias.append({
                    "id_garantia": f"GAR-{garantia_counter:05d}",
                    "id_prestamo": loan["id_prestamo"],
                    "id_garante": controllers[i],
                    "tipo_garantia": "AVAL",
                    "cobertura_porcentaje": round(random.uniform(0.25, 0.75), 2),
                    "fecha_inicio": loan["fecha_inicio"],
                    "fecha_vencimiento": loan["fecha_vencimiento"],
                    "activa": True,
                })

    # Rule 3: Random guarantees to fill up to target
    all_client_ids = [c["id_cliente"] for c in clientes]
    all_active_loans = [p for p in prestamos if p["estatus"] in ("ACTIVO", "REESTRUCTURADO")]

    n_random = max(40, target - len(garantias))
    for _ in range(n_random):
        garante = random.choice(all_client_ids)
        loan = random.choice(all_active_loans)
        # Don't guarantee your own loan
        if loan["id_titular"] == garante:
            continue
        garantia_counter += 1
        garantias.append({
            "id_garantia": f"GAR-{garantia_counter:05d}",
            "id_prestamo": loan["id_prestamo"],
            "id_garante": garante,
            "tipo_garantia": random.choice(tipos),
            "cobertura_porcentaje": round(random.uniform(0.25, 1.0), 2),
            "fecha_inicio": loan["fecha_inicio"],
            "fecha_vencimiento": loan["fecha_vencimiento"],
            "activa": True,
        })

    # Trim to target if overshot
    if len(garantias) > target:
        garantias = random.sample(garantias, target)

    return garantias


# ---------------------------------------------------------------------------
# Step 5: Generate Relaciones Empresariales
# ---------------------------------------------------------------------------
def generate_relaciones(
    clientes: list[dict],
    empresas: list[dict],
    psc_rels: list[dict],
) -> list[dict]:
    """Map PSC control edges to ES_ACCIONISTA_DE / ES_DIRECTOR_DE."""

    psc_to_cliente = {c["_psc_person_id"]: c["id_cliente"] for c in clientes}
    psc_to_empresa = {e["_psc_company_ref"]: e["id_empresa"] for e in empresas}

    relaciones = []
    rel_counter = 0

    for rel in psc_rels:
        if rel["rel_type"] != "CONTROLS":
            continue
        cliente_id = psc_to_cliente.get(rel["from_id"])
        empresa_id = psc_to_empresa.get(rel["to_id"])
        if not cliente_id or not empresa_id:
            continue

        rel_counter += 1

        # Decide relationship type: 70% accionista, 30% director
        if random.random() < 0.70:
            tipo = "ACCIONISTA"
            participacion = round(random.uniform(0.05, 1.0), 2)
        else:
            tipo = "DIRECTOR"
            participacion = ""

        fecha_inicio = fake.date_between(start_date="-10y", end_date="-1y").isoformat()

        relaciones.append({
            "id_relacion": f"REL-{rel_counter:05d}",
            "id_individuo": cliente_id,
            "id_empresa": empresa_id,
            "tipo_relacion": tipo,
            "porcentaje_participacion": participacion,
            "fecha_inicio": fecha_inicio,
            "fecha_fin": "",  # NULL means currently active
            "activa": True,
        })

    return relaciones


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------
def write_csv(data: list[dict], filepath: Path):
    """Write list of dicts to CSV, excluding metadata fields (starting with _)."""
    if not data:
        log.warning(f"No data to write to {filepath}")
        return

    # Filter out internal metadata fields
    fieldnames = [k for k in data[0].keys() if not k.startswith("_")]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)

    log.info(f"  Wrote {len(data)} rows to {filepath}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load source data
    persons = load_json("subgraph_persons.json")
    companies = load_json("subgraph_companies.json")
    rels = load_json("subgraph_relationships.json")
    gleif_entities = load_json("gleif_mx_entities.json")

    psc_rels = [r for r in rels if r["rel_type"] == "CONTROLS"]

    # Step 1: ClienteIndividual
    log.info("=" * 60)
    log.info("Step 1: Generating ClienteIndividual (300 persons)")
    log.info("=" * 60)
    clientes = generate_clientes(persons)
    log.info(f"  Generated {len(clientes)} clientes")

    # Step 2: Empresas
    log.info("=" * 60)
    log.info(f"Step 2: Generating Empresas ({TARGET_EMPRESAS} companies)")
    log.info("=" * 60)
    empresas = generate_empresas(companies, gleif_entities, TARGET_EMPRESAS)
    log.info(f"  Generated {len(empresas)} empresas")

    # Step 3: Prestamos
    log.info("=" * 60)
    log.info(f"Step 3: Generating Prestamos ({TARGET_PRESTAMOS} loans)")
    log.info("=" * 60)
    prestamos = generate_prestamos(clientes, empresas, TARGET_PRESTAMOS)

    # Stats
    status_counts = {}
    for p in prestamos:
        status_counts[p["estatus"]] = status_counts.get(p["estatus"], 0) + 1
    log.info(f"  Generated {len(prestamos)} prestamos")
    for status, count in sorted(status_counts.items()):
        log.info(f"    {status}: {count} ({count/len(prestamos)*100:.1f}%)")

    individual = sum(1 for p in prestamos if p["tipo_titular"] == "INDIVIDUAL")
    log.info(f"  Individual: {individual}, Corporate: {len(prestamos) - individual}")

    # Step 4: Garantias
    log.info("=" * 60)
    log.info(f"Step 4: Generating Garantias ({TARGET_GARANTIAS} guarantees)")
    log.info("=" * 60)
    garantias = generate_garantias(clientes, empresas, prestamos, psc_rels, TARGET_GARANTIAS)
    log.info(f"  Generated {len(garantias)} garantias")

    # Step 5: Relaciones Empresariales
    log.info("=" * 60)
    log.info("Step 5: Generating Relaciones Empresariales")
    log.info("=" * 60)
    relaciones = generate_relaciones(clientes, empresas, psc_rels)
    log.info(f"  Generated {len(relaciones)} relaciones")

    # Write CSVs
    log.info("=" * 60)
    log.info("Writing raw CSV files")
    log.info("=" * 60)
    write_csv(clientes, OUTPUT_DIR / "clientes_raw.csv")
    write_csv(empresas, OUTPUT_DIR / "empresas_raw.csv")
    write_csv(prestamos, OUTPUT_DIR / "prestamos_raw.csv")
    write_csv(garantias, OUTPUT_DIR / "garantias_raw.csv")
    write_csv(relaciones, OUTPUT_DIR / "relaciones_raw.csv")

    # Summary
    log.info("=" * 60)
    log.info("Done.")
    log.info(f"  Clientes:    {len(clientes)}")
    log.info(f"  Empresas:    {len(empresas)}")
    log.info(f"  Prestamos:   {len(prestamos)}")
    log.info(f"  Garantias:   {len(garantias)}")
    log.info(f"  Relaciones:  {len(relaciones)}")
    log.info(f"  Output dir:  {OUTPUT_DIR}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
