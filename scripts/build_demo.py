"""Build the offline, fictional CreditGraph investigation artifacts (stdlib only)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def bilingual(en, es):
    return {"en": en, "es": es}


def guarantee_adjacency(edges):
    """Project guarantor -> borrower; a connection is not transferred liability."""
    owners = {e["target"]: e["source"] for e in edges if e["type"] == "owns"}
    adjacency = {}
    for edge in edges:
        if edge["type"] == "guarantees" and edge["target"] in owners:
            adjacency.setdefault(edge["source"], set()).add(owners[edge["target"]])
    return adjacency


def reachable(adjacency, start):
    seen, pending = set(), [start]
    while pending:
        node = pending.pop()
        for neighbor in adjacency.get(node, ()):
            if neighbor != start and neighbor not in seen:
                seen.add(neighbor)
                pending.append(neighbor)
    return seen


def cycles(adjacency):
    """Small-fixture directed simple cycles, deduplicated by rotation."""
    found = set()
    def visit(start, path):
        for neighbor in sorted(adjacency.get(path[-1], ())):
            if neighbor == start and len(path) > 1:
                rotations = [tuple(path[i:] + path[:i]) for i in range(len(path))]
                found.add(min(rotations))
            elif neighbor not in path:
                visit(start, path + [neighbor])
    for node in sorted(adjacency):
        visit(node, [node])
    return sorted(found)


def shared_controllers(edges):
    groups = {}
    for edge in edges:
        if edge["type"] == "controls":
            groups.setdefault(edge["source"], set()).add(edge["target"])
    return {key: sorted(value) for key, value in groups.items() if len(value) >= 2}


def shareholder_hubs(edges):
    groups = {}
    for edge in edges:
        if edge["type"] == "shareholder":
            groups.setdefault(edge["target"], set()).add(edge["source"])
    return {key: sorted(value) for key, value in groups.items() if len(value) >= 3}


def metrics(loans):
    unique = {}
    for loan in loans:
        if loan["id"] in unique and unique[loan["id"]] != loan:
            raise ValueError("Conflicting duplicate loan")
        if not isinstance(loan["amount_mxn"], int) or loan["amount_mxn"] < 0:
            raise ValueError("Demo balances must be nonnegative integer MXN")
        unique[loan["id"]] = loan
    return {"exposure_mxn": sum(p["amount_mxn"] for p in unique.values()),
            "loan_count": len(unique), "borrower_count": len({p["borrower_id"] for p in unique.values()})}


def build_demo():
    scenarios = []
    def scenario(id, title, observation, consequence, review, people, companies, loan_specs, relationships, query):
        nodes = [{"id": key, "label": label, "type": "person"} for key, label in people]
        nodes += [{"id": key, "label": label, "type": "company"} for key, label in companies]
        names = {n["id"]: n["label"] for n in nodes}
        loans, edges = [], []
        for key, owner, amount, relationship in loan_specs:
            nodes.append({"id": key, "label": key, "type": "loan"})
            loans.append({"id": key, "borrower": names[owner], "borrower_id": owner,
                          "amount_mxn": amount, "relationship": relationship})
            edges.append({"source": owner, "target": key, "type": "owns"})
        edges += [{"source": a, "target": b, "type": kind} for a, b, kind in relationships]
        scenarios.append(dict(id=id, title=title, observation=observation, consequence=consequence,
                              review=review, nodes=nodes, edges=edges, loans=loans, metrics=metrics(loans), query=query))

    scenario("control", bilingual("Shared control", "Control compartido"),
        bilingual("Three companies borrow separately. The same person controls all three.",
                  "Tres empresas tienen créditos separados. Una misma persona controla las tres."),
        bilingual("MXN 1,800,000 belongs to one connected group. Shared control deserves a combined review.",
                  "MXN 1,800,000 pertenecen a un grupo conectado. El control común merece una revisión conjunta."),
        bilingual("Check group limits and dependence on the controller before assuming diversification.",
                  "Revisar los límites del grupo y la dependencia del controlador antes de asumir diversificación."),
        [("P01", "Alex Rivera")], [("C01", "Lumen"), ("C02", "Norte"), ("C03", "Prisma")],
        [("L01", "C01", 600000, bilingual("Shared controller", "Controlador común")),
         ("L02", "C02", 800000, bilingual("Shared controller", "Controlador común")),
         ("L03", "C03", 400000, bilingual("Shared controller", "Controlador común"))],
        [("P01", c, "controls") for c in ("C01", "C02", "C03")],
        "MATCH (c:Person)-[:CONTROLS]->(e:Company)\nWITH c, collect(DISTINCT e) AS companies\nWHERE size(companies) >= 2\nUNWIND companies AS e\nMATCH (e)-[:OWNS]->(p:Loan)\nWITH c, collect(DISTINCT p) AS loans\nRETURN c.id, reduce(total = 0, p IN loans | total + p.amount_mxn) AS exposure_mxn")

    scenario("chain", bilingual("Guarantee chain", "Cadena de garantías"),
        bilingual("Alex guarantees Sam’s loan. Sam guarantees Noa’s. Follow the chain to see both obligations.",
                  "Alex garantiza el crédito de Sam. Sam garantiza el de Noa. Sigue la cadena para ver ambas obligaciones."),
        bilingual("MXN 390,000 is connected. Alex’s guarantee does not automatically extend to Noa’s debt.",
                  "MXN 390,000 están conectados. La garantía de Alex no se extiende automáticamente a la deuda de Noa."),
        bilingual("Check what each guarantee covers and whether each guarantor could afford a claim.",
                  "Revisar qué cubre cada garantía y si cada garante podría responder a una reclamación."),
        [("P11", "Alex Sol"), ("P12", "Sam Vega"), ("P13", "Noa Mar")], [],
        [("L11", "P11", 90000, bilingual("Alex’s own loan", "Crédito propio de Alex")),
         ("L12", "P12", 120000, bilingual("Guaranteed by Alex", "Garantizado por Alex")),
         ("L13", "P13", 180000, bilingual("Guaranteed by Sam; indirect link to Alex", "Garantizado por Sam; vínculo indirecto con Alex"))],
        [("P11", "L12", "guarantees"), ("P12", "L13", "guarantees")],
        "// Two explicit guarantee obligations, not transferred liability\nMATCH (a:Person)-[:GUARANTEES]->(p:Loan)<-[:OWNS]-(b:Person),\n      (b)-[:GUARANTEES]->(q:Loan)<-[:OWNS]-(c:Person)\nWHERE a <> b AND b <> c AND a <> c\nRETURN DISTINCT a.id, p.id, b.id, q.id, c.id")

    scenario("cycle", bilingual("Circular guarantees", "Garantías circulares"),
        bilingual("Three borrowers guarantee one another in a closed loop. Every guarantor is inside the group.",
                  "Tres deudores se garantizan mutuamente en un ciclo cerrado. Todos los garantes están dentro del grupo."),
        bilingual("MXN 360,000 relies on support within the group. The loop alone does not establish zero recovery.",
                  "MXN 360,000 dependen del respaldo interno del grupo. El ciclo por sí solo no implica una recuperación nula."),
        bilingual("Check independent assets, collateral, and contract terms before relying on these guarantees.",
                  "Revisar activos independientes, colaterales y contratos antes de confiar en estas garantías."),
        [("P21", "Ari Luna"), ("P22", "Dani Lago"), ("P23", "Ren Cruz")], [],
        [("L21", "P21", 100000, bilingual("Guaranteed by Ren", "Garantizado por Ren")),
         ("L22", "P22", 120000, bilingual("Guaranteed by Ari", "Garantizado por Ari")),
         ("L23", "P23", 140000, bilingual("Guaranteed by Dani", "Garantizado por Dani"))],
        [("P21", "L22", "guarantees"), ("P22", "L23", "guarantees"), ("P23", "L21", "guarantees")],
        "MATCH (a:Person)-[:GUARANTEES]->(p:Loan)<-[:OWNS]-(b:Person),\n      (b)-[:GUARANTEES]->(q:Loan)<-[:OWNS]-(c:Person),\n      (c)-[:GUARANTEES]->(r:Loan)<-[:OWNS]-(a)\nWHERE a.id < b.id AND a.id < c.id AND b <> c\nRETURN a.id, b.id, c.id, p.id, q.id, r.id")

    scenario("hub", bilingual("Company hub", "Empresa compartida"),
        bilingual("One company connects three shareholders with personal loans. Two also guarantee each other.",
                  "Una empresa conecta a tres accionistas con créditos personales. Dos también se garantizan mutuamente."),
        bilingual("MXN 1,650,000 is linked to the company and its shareholders. Ownership signals a dependency, not a measured loss.",
                  "MXN 1,650,000 están vinculados a la empresa y sus accionistas. La participación indica dependencia, no una pérdida medida."),
        bilingual("Check income dependence, liquidity, and direct guarantees. Count each loan once, even across multiple paths.",
                  "Revisar dependencia de ingresos, liquidez y garantías directas. Contar cada crédito una vez, aunque existan varias rutas."),
        [("P31", "Sol Alba"), ("P32", "Cris Ríos"), ("P33", "Paz Sierra")], [("C31", "Faro")],
        [("L31", "C31", 1200000, bilingual("Company’s own loan", "Crédito de la empresa")),
         ("L32", "P31", 150000, bilingual("Shareholder; guaranteed by Cris", "Accionista; garantizado por Cris")),
         ("L33", "P32", 200000, bilingual("Shareholder; guaranteed by Sol", "Accionista; garantizado por Sol")),
         ("L34", "P33", 100000, bilingual("Shareholder’s own loan", "Crédito de accionista"))],
        [(p, "C31", "shareholder") for p in ("P31", "P32", "P33")] + [("P31", "L33", "guarantees"), ("P32", "L32", "guarantees")],
        "MATCH (e:Company {id: 'C31'})\nOPTIONAL MATCH (c:Person)-[:SHAREHOLDER]->(e)\nWITH e, collect(DISTINCT c) + [e] AS borrowers\nUNWIND borrowers AS borrower\nMATCH (borrower)-[:OWNS]->(p:Loan)\nWITH collect(DISTINCT p) AS loans\nRETURN size(loans) AS loan_count,\n       reduce(total = 0, p IN loans | total + p.amount_mxn) AS exposure_mxn")
    result = {"version": 1, "provenance": {"kind": "fully_synthetic", "reference_date": "2026-01-01",
              "generator": "scripts/build_demo.py", "currency": "MXN", "seed": 42,
              "description": "Fixed fictional fixtures; no real company finances, live database, or empirical findings.",
              "query_schema": "Illustrative Neo4j mapping: Person/Company/Loan nodes, OWNS/GUARANTEES/CONTROLS/SHAREHOLDER edges; distinct from historical Spanish schema."},
              "scenarios": scenarios}
    validate(result)
    return result


def validate(demo):
    for scenario in demo["scenarios"]:
        ids = [n["id"] for n in scenario["nodes"]]
        assert len(ids) == len(set(ids))
        assert all(e["source"] in ids and e["target"] in ids for e in scenario["edges"])
        assert scenario["metrics"] == metrics(scenario["loans"])
        assert len({p["id"] for p in scenario["loans"]}) == len(scenario["loans"])
        owners = [e["target"] for e in scenario["edges"] if e["type"] == "owns"]
        assert sorted(owners) == sorted(p["id"] for p in scenario["loans"])
        graph = guarantee_adjacency(scenario["edges"])
        if scenario["id"] == "control":
            assert shared_controllers(scenario["edges"])
        elif scenario["id"] == "chain":
            assert reachable(graph, "P11") == {"P12", "P13"} and not cycles(graph)
        elif scenario["id"] == "cycle":
            assert len(cycles(graph)) == 1
        elif scenario["id"] == "hub":
            assert shareholder_hubs(scenario["edges"]) and cycles(graph)


def main():
    target = ROOT / "web/data/demo.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_demo(), ensure_ascii=False, indent=2) + "\n")
    print(f"Built {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
