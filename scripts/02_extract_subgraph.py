"""
02_extract_subgraph.py
----------------------
Builds a NetworkX graph from GLEIF + PSC data, finds the most connected
subgraph, and selects ~300 persons + ~80 companies for the CreditGraph.

Strategy:
  1. Load PSC persons, companies, and relationships
  2. Build a bipartite graph: Person nodes <-> Company nodes
  3. Find connected components (clusters where persons share companies)
  4. Select the largest components until we reach ~80 companies
  5. Include all persons connected to those companies
  6. Merge with GLEIF company-to-company relationships
  7. Output the selected subgraph

Output:
  data/source/subgraph_persons.json       -- Selected persons (~300)
  data/source/subgraph_companies.json     -- Selected companies (~80)
  data/source/subgraph_relationships.json -- All edges (person→company + company→company)
  data/source/subgraph_stats.json         -- Connectivity statistics
"""

import json
import logging
from pathlib import Path
from collections import Counter

import networkx as nx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SOURCE_DIR = Path(__file__).resolve().parent.parent / "data" / "source"
TARGET_COMPANIES = 80
TARGET_PERSONS = 300

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Load source data
# ---------------------------------------------------------------------------
def load_json(filename: str) -> list[dict]:
    path = SOURCE_DIR / filename
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    # ------------------------------------------------------------------
    # Step 1: Load all source data
    # ------------------------------------------------------------------
    log.info("=" * 60)
    log.info("Step 1: Loading source data")
    log.info("=" * 60)

    psc_persons = load_json("psc_persons.json")
    psc_companies = load_json("psc_companies.json")
    psc_rels = load_json("psc_relationships.json")
    gleif_entities = load_json("gleif_mx_entities.json")
    gleif_rels = load_json("gleif_relationships.json")

    log.info(f"  PSC persons:       {len(psc_persons)}")
    log.info(f"  PSC companies:     {len(psc_companies)}")
    log.info(f"  PSC relationships: {len(psc_rels)}")
    log.info(f"  GLEIF entities:    {len(gleif_entities)}")
    log.info(f"  GLEIF rels:        {len(gleif_rels)}")

    # Build lookup maps
    person_by_id = {p["person_id"]: p for p in psc_persons}
    company_refs = {c["company_ref"] for c in psc_companies}

    # ------------------------------------------------------------------
    # Step 2: Build bipartite graph
    # ------------------------------------------------------------------
    log.info("=" * 60)
    log.info("Step 2: Building bipartite graph (persons <-> companies)")
    log.info("=" * 60)

    G = nx.Graph()

    # Add person nodes
    for p in psc_persons:
        G.add_node(
            p["person_id"],
            node_type="person",
            fullname=p["fullname"],
            birthdate=p.get("birthdate", ""),
            company_count=p["company_count"],
        )

    # Add company nodes and edges
    for rel in psc_rels:
        comp_ref = rel["company_ref"]
        person_id = rel["person_id"]

        if not G.has_node(comp_ref):
            G.add_node(comp_ref, node_type="company")

        G.add_edge(person_id, comp_ref, edge_type="CONTROLS")

    log.info(f"  Graph nodes: {G.number_of_nodes()}")
    log.info(f"  Graph edges: {G.number_of_edges()}")

    # ------------------------------------------------------------------
    # Step 3: Find connected components
    # ------------------------------------------------------------------
    log.info("=" * 60)
    log.info("Step 3: Finding connected components")
    log.info("=" * 60)

    components = sorted(nx.connected_components(G), key=len, reverse=True)
    log.info(f"  Total components: {len(components)}")

    # Analyze top components
    for i, comp in enumerate(components[:10]):
        persons_in = sum(1 for n in comp if G.nodes[n].get("node_type") == "person")
        companies_in = sum(1 for n in comp if G.nodes[n].get("node_type") == "company")
        log.info(
            f"  Component {i+1}: {len(comp)} nodes "
            f"({persons_in} persons, {companies_in} companies)"
        )

    # ------------------------------------------------------------------
    # Step 4: Select subgraph -- company-first, then fill persons
    # ------------------------------------------------------------------
    log.info("=" * 60)
    log.info("Step 4: Selecting subgraph (company-first strategy)")
    log.info("=" * 60)

    selected_persons = set()
    selected_companies = set()

    # Build lookup: company -> set of persons controlling it
    company_to_persons = {}
    person_to_companies = {}
    for rel in psc_rels:
        comp = rel["company_ref"]
        pid = rel["person_id"]
        company_to_persons.setdefault(comp, set()).add(pid)
        person_to_companies.setdefault(pid, set()).add(comp)

    # Priority 1: Companies with 2+ controllers (shared directors)
    shared = {c for c, ps in company_to_persons.items() if len(ps) >= 2}
    selected_companies.update(shared)
    for c in shared:
        selected_persons.update(company_to_persons[c])
    log.info(
        f"  After shared-director companies: "
        f"{len(selected_companies)} companies, {len(selected_persons)} persons"
    )

    # Priority 2: Companies controlled by already-selected persons
    # (these create cross-connections in the graph)
    for pid in list(selected_persons):
        for comp in person_to_companies.get(pid, set()):
            if len(selected_companies) < TARGET_COMPANIES:
                selected_companies.add(comp)
    log.info(
        f"  After expanding from shared persons: "
        f"{len(selected_companies)} companies"
    )

    # Priority 3: If still under target, add companies from largest components
    if len(selected_companies) < TARGET_COMPANIES:
        for comp in components:
            if len(selected_companies) >= TARGET_COMPANIES:
                break
            companies_in_comp = {
                n for n in comp if G.nodes[n].get("node_type") == "company"
            }
            persons_in_comp = {
                n for n in comp if G.nodes[n].get("node_type") == "person"
            }
            # Only add companies, limit to a few per component
            new_companies = companies_in_comp - selected_companies
            if new_companies:
                to_add = list(new_companies)[:max(1, TARGET_COMPANIES - len(selected_companies))]
                selected_companies.update(to_add)
                selected_persons.update(persons_in_comp)

    # Trim companies to target if we overshot
    if len(selected_companies) > TARGET_COMPANIES:
        # Keep shared-director companies, trim the rest
        non_shared = selected_companies - shared
        excess = len(selected_companies) - TARGET_COMPANIES
        to_remove = list(non_shared)[:excess]
        selected_companies -= set(to_remove)

    # Fill persons: include all persons who control at least one selected company
    for pid, comps in person_to_companies.items():
        if comps & selected_companies:
            selected_persons.add(pid)
        if len(selected_persons) >= TARGET_PERSONS:
            break

    # If still under target persons, add remaining persons (no company overlap)
    if len(selected_persons) < TARGET_PERSONS:
        remaining = [p for p in psc_persons if p["person_id"] not in selected_persons]
        remaining.sort(key=lambda x: x["company_count"], reverse=True)
        for p in remaining:
            selected_persons.add(p["person_id"])
            # Add ONE of their companies (not all -- keeps company count controlled)
            person_comps = person_to_companies.get(p["person_id"], set())
            if person_comps:
                selected_companies.add(next(iter(person_comps)))
            if len(selected_persons) >= TARGET_PERSONS:
                break

    log.info(f"  Final: {len(selected_persons)} persons, {len(selected_companies)} companies")

    # ------------------------------------------------------------------
    # Step 5: Extract subgraph data
    # ------------------------------------------------------------------
    log.info("=" * 60)
    log.info("Step 5: Extracting subgraph data")
    log.info("=" * 60)

    # Persons
    out_persons = []
    for p in psc_persons:
        if p["person_id"] in selected_persons:
            out_persons.append(p)

    # Companies -- combine PSC company refs with any matching GLEIF data
    gleif_by_lei = {e["lei"]: e for e in gleif_entities}
    out_companies = []
    for comp_ref in sorted(selected_companies):
        parts = comp_ref.split("-")
        company_number = parts[-1] if len(parts) >= 3 else comp_ref

        company_record = {
            "company_ref": comp_ref,
            "company_number": company_number,
            "source": "PSC",
        }
        out_companies.append(company_record)

    # Relationships: person→company (from PSC)
    out_rels = []
    for rel in psc_rels:
        if (rel["person_id"] in selected_persons and
                rel["company_ref"] in selected_companies):
            out_rels.append({
                "from_id": rel["person_id"],
                "from_type": "person",
                "to_id": rel["company_ref"],
                "to_type": "company",
                "rel_type": "CONTROLS",
            })

    # Relationships: company→company (from GLEIF)
    # Map GLEIF parent-child edges into our subgraph
    gleif_company_edges = 0
    for grel in gleif_rels:
        out_rels.append({
            "from_id": grel["child_lei"],
            "from_type": "gleif_company",
            "to_id": grel["parent_lei"],
            "to_type": "gleif_company",
            "rel_type": "IS_SUBSIDIARY_OF",
            "rel_status": grel.get("rel_status", ""),
        })
        gleif_company_edges += 1

    log.info(f"  Persons:              {len(out_persons)}")
    log.info(f"  Companies (PSC):      {len(out_companies)}")
    log.info(f"  Person→Company edges: {len(out_rels) - gleif_company_edges}")
    log.info(f"  GLEIF company edges:  {gleif_company_edges}")
    log.info(f"  Total edges:          {len(out_rels)}")

    # ------------------------------------------------------------------
    # Step 6: Compute connectivity stats
    # ------------------------------------------------------------------
    log.info("=" * 60)
    log.info("Step 6: Connectivity statistics")
    log.info("=" * 60)

    # Build subgraph for stats
    all_selected = selected_persons | selected_companies
    SG = G.subgraph(all_selected & set(G.nodes()))
    sub_components = list(nx.connected_components(SG))

    # Companies with multiple controllers (shared directors)
    company_controller_counts = Counter()
    for rel in out_rels:
        if rel["rel_type"] == "CONTROLS":
            company_controller_counts[rel["to_id"]] += 1
    shared_companies = sum(1 for c in company_controller_counts.values() if c >= 2)

    # Persons controlling multiple companies
    person_company_counts = Counter()
    for rel in out_rels:
        if rel["rel_type"] == "CONTROLS":
            person_company_counts[rel["from_id"]] += 1
    multi_controllers = sum(1 for c in person_company_counts.values() if c >= 2)

    stats = {
        "total_persons": len(out_persons),
        "total_companies": len(out_companies),
        "total_psc_edges": len(out_rels) - gleif_company_edges,
        "total_gleif_edges": gleif_company_edges,
        "connected_components": len(sub_components),
        "largest_component_size": len(sub_components[0]) if sub_components else 0,
        "companies_with_shared_directors": shared_companies,
        "persons_controlling_multiple_companies": multi_controllers,
        "avg_companies_per_person": round(
            sum(person_company_counts.values()) / max(len(person_company_counts), 1), 2
        ),
        "avg_controllers_per_company": round(
            sum(company_controller_counts.values()) / max(len(company_controller_counts), 1), 2
        ),
    }

    for key, val in stats.items():
        log.info(f"  {key}: {val}")

    # ------------------------------------------------------------------
    # Step 7: Save
    # ------------------------------------------------------------------
    log.info("=" * 60)
    log.info("Saving subgraph")
    log.info("=" * 60)

    for data, filename in [
        (out_persons, "subgraph_persons.json"),
        (out_companies, "subgraph_companies.json"),
        (out_rels, "subgraph_relationships.json"),
        (stats, "subgraph_stats.json"),
    ]:
        path = SOURCE_DIR / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        count = len(data) if isinstance(data, list) else "1 object"
        log.info(f"  Saved {count} to {path}")

    log.info("=" * 60)
    log.info("Done.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
