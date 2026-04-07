"""
04b_add_gleif_hierarchy.py
--------------------------
Adds GLEIF corporate parent-child relationships as a separate layer
in the graph. Picks 3-4 real Mexican financial/industrial groups,
adds parent + child companies as new Empresa nodes, and creates
ES_SUBSIDIARIA_DE relationships between them.

These are REAL Mexican corporate structures from GLEIF:
  - BBVA Asset Management Mexico (15 investment fund subsidiaries)
  - Grupo Bimbo (Barcel, Ricolino, etc.)
  - Selected others with resolvable child names

This layer is SEPARATE from the PSC person→company layer.
It demonstrates corporate group contagion: if the parent fails,
all subsidiaries are exposed.

Output: modifies data/raw/empresas_raw.csv and data/raw/relaciones_raw.csv
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
SEED = 99
random.seed(SEED)
np.random.seed(SEED)

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
    if not data:
        return
    path = RAW_DIR / filename
    fieldnames = list(data[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    log.info(f"  Wrote {len(data)} rows to {path}")


def generate_rfc(name, years_ago):
    """Quick RFC generator for corporate entities."""
    words = [w for w in name.upper().split() if w not in ("SA", "DE", "CV", "SAPI", "SAB", "S.A.", "S.A.B.")]
    prefix = ""
    for w in words[:3]:
        if w:
            prefix += w[0]
    prefix = prefix.ljust(3, "X")[:3]
    d = date.today() - timedelta(days=years_ago * 365)
    date_part = d.strftime("%y%m%d")
    homo = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=3))
    return prefix + date_part + homo


def main():
    # Load GLEIF data
    with open(SOURCE_DIR / "gleif_mx_entities.json") as f:
        gleif_entities = json.load(f)
    with open(SOURCE_DIR / "gleif_relationships.json") as f:
        gleif_rels = json.load(f)

    gleif_by_lei = {e["lei"]: e for e in gleif_entities}

    # Load existing CSVs
    empresas = load_csv("empresas_raw.csv")
    prestamos = load_csv("prestamos_raw.csv")
    relaciones = load_csv("relaciones_raw.csv")

    existing_emp_ids = {e["id_empresa"] for e in empresas}
    max_emp_num = max(int(e["id_empresa"].split("-")[1]) for e in empresas)

    # ================================================================
    # Select 3 well-known MX parent groups with resolvable child names
    # ================================================================

    # Group 1: BBVA Asset Management Mexico
    bbva_parent_lei = "4469000001BLWL1EXG90"
    # Group 2: Grupo Bimbo
    bimbo_parent_lei = "5493000RIXURZEBFEV60"
    # Group 3: Find another MX parent with named children
    # Look for MX parents whose children also have names in GLEIF
    mx_parents_with_named_children = []
    for parent_lei in set(r["parent_lei"] for r in gleif_rels):
        if parent_lei not in gleif_by_lei:
            continue  # skip non-MX parents
        children = [r["child_lei"] for r in gleif_rels if r["parent_lei"] == parent_lei]
        named_children = [c for c in children if c in gleif_by_lei]
        if len(named_children) >= 3 and parent_lei not in (bbva_parent_lei, bimbo_parent_lei):
            mx_parents_with_named_children.append(
                (parent_lei, gleif_by_lei[parent_lei]["legal_name"], len(named_children))
            )

    mx_parents_with_named_children.sort(key=lambda x: x[2], reverse=True)
    third_group_lei = mx_parents_with_named_children[0][0] if mx_parents_with_named_children else None

    groups_to_add = [
        (bbva_parent_lei, 5),    # BBVA: parent + 5 subsidiaries
        (bimbo_parent_lei, 4),   # Bimbo: parent + 4 subsidiaries
    ]
    if third_group_lei:
        groups_to_add.append((third_group_lei, 3))

    log.info("=" * 60)
    log.info("Adding GLEIF corporate hierarchy groups")
    log.info("=" * 60)

    new_empresas = []
    new_relaciones = []
    new_prestamos = []
    lei_to_emp_id = {}

    sectors = {"BBVA": "SERVICIOS", "BIMBO": "MANUFACTURA", "BARCEL": "MANUFACTURA",
               "RICOLINO": "MANUFACTURA", "FONDO": "SERVICIOS"}

    for parent_lei, max_children in groups_to_add:
        parent_entity = gleif_by_lei.get(parent_lei, {})
        parent_name = parent_entity.get("legal_name", "?")
        parent_region = parent_entity.get("address_region", "MX-CMX")
        parent_rfc = parent_entity.get("registered_as", "")

        log.info(f"\n  GROUP: {parent_name[:55]}")

        # Create parent Empresa
        max_emp_num += 1
        parent_emp_id = f"EMP-{max_emp_num:05d}"
        lei_to_emp_id[parent_lei] = parent_emp_id

        # Determine sector from name keywords
        sector = "SERVICIOS"
        for kw, sec in sectors.items():
            if kw in parent_name.upper():
                sector = sec
                break

        new_empresas.append({
            "id_empresa": parent_emp_id,
            "razon_social": parent_name,
            "rfc": parent_rfc if parent_rfc else generate_rfc(parent_name, 20),
            "sector": sector,
            "tamano": "GRANDE",
            "ingresos_anuales_mxn": round(float(np.random.lognormal(17, 0.5)), 2),
            "anos_operacion": random.randint(15, 40),
            "num_empleados": random.randint(500, 5000),
            "estado_registro": parent_region.replace("MX-", "") if parent_region.startswith("MX-") else "CDMX",
        })
        log.info(f"    Parent: {parent_emp_id} = {parent_name[:50]}")

        # Create a loan for the parent
        pre_num = max(int(p["id_prestamo"].split("-")[1]) for p in prestamos + new_prestamos) + 1
        new_prestamos.append({
            "id_prestamo": f"PRE-{pre_num:05d}",
            "id_titular": parent_emp_id,
            "tipo_titular": "EMPRESA",
            "monto_original_mxn": round(float(np.random.lognormal(16, 0.8)), 2),
            "saldo_vigente_mxn": round(float(np.random.lognormal(15.5, 0.8)), 2),
            "tasa_interes_anual": round(random.uniform(0.06, 0.12), 4),
            "fecha_inicio": (date.today() - timedelta(days=random.randint(200, 800))).isoformat(),
            "fecha_vencimiento": (date.today() + timedelta(days=random.randint(500, 2000))).isoformat(),
            "estatus": "ACTIVO",
            "dias_mora": 0,
            "probabilidad_incumplimiento": "",
            "score_version": "",
            "score_fecha": "",
        })

        # Get children for this parent
        children_leis = [r["child_lei"] for r in gleif_rels if r["parent_lei"] == parent_lei]
        # Only use children that have names in GLEIF
        named_children = [(c, gleif_by_lei[c]) for c in children_leis if c in gleif_by_lei]

        for child_lei, child_entity in named_children[:max_children]:
            max_emp_num += 1
            child_emp_id = f"EMP-{max_emp_num:05d}"
            lei_to_emp_id[child_lei] = child_emp_id

            child_name = child_entity["legal_name"]
            child_rfc = child_entity.get("registered_as", "")

            child_sector = sector  # inherit from parent
            for kw, sec in sectors.items():
                if kw in child_name.upper():
                    child_sector = sec

            new_empresas.append({
                "id_empresa": child_emp_id,
                "razon_social": child_name,
                "rfc": child_rfc if child_rfc else generate_rfc(child_name, random.randint(5, 25)),
                "sector": child_sector,
                "tamano": random.choice(["MEDIANA", "GRANDE"]),
                "ingresos_anuales_mxn": round(float(np.random.lognormal(15, 0.8)), 2),
                "anos_operacion": random.randint(5, 30),
                "num_empleados": random.randint(50, 1000),
                "estado_registro": child_entity.get("address_region", "MX-CMX").replace("MX-", ""),
            })

            # Create subsidiary relationship
            rel_num = max(
                int(r["id_relacion"].split("-")[1])
                for r in relaciones + new_relaciones
            ) + 1
            new_relaciones.append({
                "id_relacion": f"REL-{rel_num:05d}",
                "id_individuo": child_emp_id,  # child empresa (acts as "individuo" in this edge)
                "id_empresa": parent_emp_id,    # parent empresa
                "tipo_relacion": "SUBSIDIARIA",
                "porcentaje_participacion": 1.0,  # wholly owned
                "fecha_inicio": (date.today() - timedelta(days=random.randint(365, 3000))).isoformat(),
                "fecha_fin": "",
                "activa": True,
            })

            # Create a loan for each child
            pre_num += 1
            new_prestamos.append({
                "id_prestamo": f"PRE-{pre_num:05d}",
                "id_titular": child_emp_id,
                "tipo_titular": "EMPRESA",
                "monto_original_mxn": round(float(np.random.lognormal(14.5, 0.8)), 2),
                "saldo_vigente_mxn": round(float(np.random.lognormal(14.0, 0.8)), 2),
                "tasa_interes_anual": round(random.uniform(0.06, 0.15), 4),
                "fecha_inicio": (date.today() - timedelta(days=random.randint(100, 600))).isoformat(),
                "fecha_vencimiento": (date.today() + timedelta(days=random.randint(400, 1500))).isoformat(),
                "estatus": "ACTIVO",
                "dias_mora": 0,
                "probabilidad_incumplimiento": "",
                "score_version": "",
                "score_fecha": "",
            })

            log.info(f"    Child:  {child_emp_id} = {child_name[:50]}")

    # Merge into existing data
    empresas.extend(new_empresas)
    relaciones.extend(new_relaciones)
    prestamos.extend(new_prestamos)

    # Write updated CSVs
    log.info("\n" + "=" * 60)
    log.info("Writing updated CSVs")
    log.info("=" * 60)
    write_csv(empresas, "empresas_raw.csv")
    write_csv(relaciones, "relaciones_raw.csv")
    write_csv(prestamos, "prestamos_raw.csv")

    log.info(f"\n  Added {len(new_empresas)} empresa nodes (parents + subsidiaries)")
    log.info(f"  Added {len(new_relaciones)} ES_SUBSIDIARIA_DE edges")
    log.info(f"  Added {len(new_prestamos)} loans for new empresas")
    log.info(f"  Total empresas: {len(empresas)}")
    log.info(f"  Total relaciones: {len(relaciones)}")
    log.info(f"  Total prestamos: {len(prestamos)}")

    # Save mapping for documentation
    mapping = {
        "groups_added": [
            {
                "parent_lei": lei,
                "parent_emp_id": lei_to_emp_id.get(lei, "?"),
                "parent_name": gleif_by_lei.get(lei, {}).get("legal_name", "?"),
                "children_count": max_c,
            }
            for lei, max_c in groups_to_add
        ],
        "lei_to_emp_id": lei_to_emp_id,
        "total_new_empresas": len(new_empresas),
        "total_new_edges": len(new_relaciones),
    }
    with open(SOURCE_DIR / "gleif_hierarchy_mapping.json", "w") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
