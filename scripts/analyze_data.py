"""Analyze the acquired data to understand what we have."""
import json
from collections import Counter
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "data" / "source"


def load(name):
    with open(SOURCE / name) as f:
        return json.load(f)


def main():
    persons = load("subgraph_persons.json")
    companies = load("subgraph_companies.json")
    rels = load("subgraph_relationships.json")

    psc_edges = [r for r in rels if r["rel_type"] == "CONTROLS"]
    gleif_edges = [r for r in rels if r["rel_type"] == "IS_SUBSIDIARY_OF"]

    # ======================
    # PERSONS
    # ======================
    print("=" * 70)
    print("PERSONS: Who are these 300 people?")
    print("=" * 70)

    person_company_count = Counter()
    person_companies = {}
    for e in psc_edges:
        person_company_count[e["from_id"]] += 1
        person_companies.setdefault(e["from_id"], []).append(e["to_id"])

    counts = list(person_company_count.values())
    print(f"\nHow many companies does each person control?")
    print(f"  1 company:     {sum(1 for c in counts if c == 1)} persons")
    print(f"  2 companies:   {sum(1 for c in counts if c == 2)} persons")
    print(f"  3-5 companies: {sum(1 for c in counts if 3 <= c <= 5)} persons")
    print(f"  6+ companies:  {sum(1 for c in counts if c >= 6)} persons")

    person_lookup = {p["person_id"]: p for p in persons}
    print(f"\nTop 10 multi-company controllers:")
    for pid, count in person_company_count.most_common(10):
        p = person_lookup.get(pid, {})
        name = p.get("fullname", "?")
        birth = p.get("birthdate", "?")
        print(f"  {name:35s} born {str(birth):10s} -> {count} companies")

    # ======================
    # COMPANIES
    # ======================
    print("\n" + "=" * 70)
    print("COMPANIES: How are the 366 companies connected?")
    print("=" * 70)

    company_controller_count = Counter()
    company_controllers = {}
    for e in psc_edges:
        company_controller_count[e["to_id"]] += 1
        company_controllers.setdefault(e["to_id"], []).append(e["from_id"])

    cc = list(company_controller_count.values())
    print(f"\nHow many controllers does each company have?")
    print(f"  1 controller:  {sum(1 for c in cc if c == 1)} companies")
    print(f"  2 controllers: {sum(1 for c in cc if c == 2)} companies")
    print(f"  3+ controllers:{sum(1 for c in cc if c >= 3)} companies")
    no_psc = len(companies) - len(company_controller_count)
    print(f"  0 controllers: {no_psc} companies (GLEIF-only, no PSC edge)")

    print(f"\nShared-director companies (2+ controllers):")
    for comp_ref, count in company_controller_count.most_common(30):
        if count < 2:
            break
        names = []
        for pid in company_controllers[comp_ref]:
            p = person_lookup.get(pid, {})
            names.append(p.get("fullname", "?"))
        comp_num = comp_ref.split("-")[-1] if "-" in comp_ref else comp_ref
        print(f"  Company {comp_num}: {' + '.join(names)}")

    # ======================
    # GRAPH PATTERNS
    # ======================
    print("\n" + "=" * 70)
    print("GRAPH PATTERNS: What topology did we capture?")
    print("=" * 70)

    # Persons connected through shared companies
    shared_pairs = []
    for comp_ref, controllers in company_controllers.items():
        if len(controllers) >= 2:
            for i in range(len(controllers)):
                for j in range(i + 1, len(controllers)):
                    p1 = person_lookup.get(controllers[i], {}).get("fullname", "?")
                    p2 = person_lookup.get(controllers[j], {}).get("fullname", "?")
                    shared_pairs.append((p1, p2, comp_ref))

    print(f"\nPerson-pairs connected through shared companies: {len(shared_pairs)}")
    print("These pairs would be 'partes relacionadas' in Mexican credit regulation.")
    for p1, p2, comp in shared_pairs[:8]:
        comp_num = comp.split("-")[-1] if "-" in comp else comp
        print(f"  {p1} <--[co-control]--> {p2}  (company {comp_num})")

    # ======================
    # WHY THIS MATTERS FOR CREDIT RISK
    # ======================
    print("\n" + "=" * 70)
    print("WHY THIS MATTERS FOR CREDIT RISK")
    print("=" * 70)

    print(f"""
The topology we captured creates these credit risk scenarios:

1. CONCENTRATION RISK (partes relacionadas):
   {len(shared_pairs)} person-pairs share control of companies.
   If Company X defaults, BOTH controllers are affected.
   Their personal loans become correlated -- not independent.
   A bank that treats their loans as independent UNDERESTIMATES risk.

2. CONTAGION PATHS:
   Person A controls Company X AND Company Y.
   If Company X defaults -> Person A's net worth drops ->
   Person A may default on personal loan ->
   Person A may stop supporting Company Y ->
   Company Y's credit quality drops.
   This is a 3-hop contagion chain. SQL can't traverse it. Cypher can.

3. GUARANTEE LOGIC (what we'll build in the synthetic layer):
   Person A is a 70% shareholder of Company X.
   Mexican banking practice: Person A GUARANTEES Company X's loan.
   Person B is a 30% shareholder of Company X.
   Person B ALSO guarantees Company X's loan.
   If Company X defaults -> guarantee activates ->
   Person A and B are now exposed -> their personal loans are at risk.

   This is EXACTLY why Prestamo must be a NODE (not a property):
   The guarantee relationship connects Person A to Company X's LOAN.
   If the loan were just a property on a (:Person)-[:OWES]->(:Bank) edge,
   the guarantee would have nowhere to attach.

4. WHAT WE HAVE vs WHAT WE NEED TO BUILD:

   REAL (from data):                SYNTHETIC (to build):
   - 300 persons                    - Mexican identities (CURP, RFC)
   - 366 companies                  - 450 loans attached to entities
   - 387 control edges              - 180 guarantees following topology
   - 21 shared-director companies   - Default labels (~4% NPL)
   - {len(shared_pairs)} related-party pairs     - Credit scores, income levels
   - GLEIF corporate hierarchies    - Data quality issues
""")

    # ======================
    # GLEIF CORPORATE CHAINS
    # ======================
    print("=" * 70)
    print("GLEIF: Corporate parent-child chains (Mexican companies)")
    print("=" * 70)

    gleif_ents = load("gleif_mx_entities.json")
    gleif_by_lei = {e["lei"]: e for e in gleif_ents}

    parent_children = {}
    for e in gleif_edges:
        parent_children.setdefault(e["to_id"], []).append(e["from_id"])

    print(f"\nTotal corporate edges: {len(gleif_edges)}")
    print(f"Unique parent groups: {len(parent_children)}")
    print(f"\nTop 5 corporate groups:")
    for parent_lei, children in sorted(
        parent_children.items(), key=lambda x: len(x[1]), reverse=True
    )[:5]:
        pname = gleif_by_lei.get(parent_lei, {}).get("legal_name", "(non-MX)")
        print(f"\n  PARENT: {pname[:60]}")
        for c in children[:4]:
            cn = gleif_by_lei.get(c, {}).get("legal_name", c[:20])
            print(f"    -> {cn[:60]}")
        if len(children) > 4:
            print(f"    ... + {len(children)-4} more subsidiaries")


if __name__ == "__main__":
    main()
