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
