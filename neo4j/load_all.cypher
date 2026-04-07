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
