'use strict';

const $ = id => document.getElementById(id);
const english = {
  "skip": "Skip to investigation",
  "navInvestigate": "Portfolio",
  "navEvidence": "Model evaluation",
  "headline": "Borrower connections",
  "intro": "Ownership and guarantees across a loan portfolio.",
  "fictional": "Synthetic data · MXN",
  "downloadDemo": "Download portfolio data",
  "investigationTitle": "Ownership and guarantees",
  "choose": "Select a relationship pattern.",
  "graphHint": "Select a person, company, or loan",
  "person": "Person",
  "company": "Company",
  "loan": "Loan",
  "observation": "Relationship",
  "consequence": "Exposure",
  "review": "Review considerations",
  "notLoss": "Balances shown are connected exposure, not estimated loss. Contract terms determine liability.",
  "loansTitle": "Loan balances",
  "dedup": "Each loan counted once",
  "loansCaption": "Affected loans and the reason for joint review",
  "borrower": "Borrower",
  "relationship": "Connection",
  "balance": "Balance (MXN)",
  "relationshipsTitle": "Relationship table",
  "from": "From",
  "to": "To",
  "queryTitle": "Cypher query",
  "queryNote": "These illustrative queries use an English schema, distinct from the historical schema. SQL can also traverse relationships recursively and detect cycles; the comparison is about clarity, not an exclusive capability.",
  "sqlDocs": "PostgreSQL recursive query documentation ↗",
  "evidenceTitle": "Model evaluation",
  "modelIntro": "Compare borrower-only and graph-enriched models under three network assumptions.",
  "modelToggle": "Results and calibration",
  "modelLimits": "The model uses a separate synthetic dataset. Evaluation covers held-out borrower groups; performance on real portfolios and later periods remains untested.",
  "methodTitle": "Data and methodology",
  "demoMethodTitle": "Portfolio data",
  "demoMethod": "The portfolio contains synthetic borrowers, loans, and relationships. Exposure is the sum of distinct outstanding loan balances; guarantee liability depends on contract terms.",
  "modelMethodTitle": "Model dataset",
  "modelMethod": "10,000 borrowers in 1,000 disconnected groups, across five fixed seeds. Whole groups are assigned to training (60%), calibration (20%), and testing (20%). Predictors use only information at the observation date; simulated defaults occur over the following 12 months.",
  "evaluationTitle": "Evaluation protocol",
  "evaluation": "A constant baseline, borrower-only logistic regression, and borrower-only and graph-enriched LightGBM are compared after sigmoid calibration. PR-AUC, ROC-AUC, Brier score, and log loss are reported with group-bootstrap uncertainty. Calibration never uses the test split.",
  "researchTitle": "Earlier public-data work",
  "research": "The repository also contains earlier public-data acquisition and notebook research. Those historical outputs are separate from this fictional demo and its synthetic experiment. No real company is assigned fictional distress here.",
  "downloadModels": "Download model results",
  "architectureTitle": "Implementation",
  "architecture": "Python generates the portfolio and model results as versioned JSON. D3 renders the relationships. The repository includes the data, configuration, and reproduction commands.",
  "source": "Source code and reproduction instructions",
  "github": "Source code",
  "loading": "Loading evidence…",
  "error": "The data could not be loaded. Serve this page through HTTP and retry.",
  "retry": "Retry",
  "graphUnavailable": "Graph unavailable. The relationship table below contains every connection.",
  "graphName": "Directed relationship graph",
  "nodePrompt": "Select a node for its relationships. Arrowheads indicate direction.",
  "exposure": "Outstanding balance · MXN",
  "loanCount": "Loans",
  "borrowerCount": "Borrowers",
  "owns": "owns",
  "guarantees": "guarantees",
  "controls": "controls",
  "shareholder": "shareholder of",
  "borrows": "borrows",
  "issued_to": "issued to",
  "connections": "connections",
  "absent": "No network effect",
  "moderate": "Moderate network effect",
  "strong": "Strong network effect",
  "constant": "Constant-rate baseline",
  "logistic_borrower": "Logistic · borrower only",
  "lightgbm_borrower": "LightGBM · borrower only",
  "lightgbm_graph": "LightGBM · graph enriched",
  "model": "Model",
  "metricNote": "Means across five seeds; brackets show 95% group-bootstrap intervals conditional on these five fitted runs. They do not capture all training or simulator uncertainty. Higher PR-AUC / ROC-AUC is better; lower Brier / log loss is better.",
  "average_precision": "PR-AUC (AP) ↑",
  "roc_auc": "ROC-AUC ↑",
  "brier": "Brier ↓",
  "log_loss": "Log loss ↓",
  "calibration": "Calibration · first fixed seed",
  "predicted": "Predicted probability",
  "observed": "Observed default rate",
  "ideal": "Perfect calibration",
  "testCounts": "Held-out positives / borrowers, by seed",
  "missing": "Unavailable",
  "uplift": "Graph minus borrower-only PR-AUC",
  "scenarioGroup": "Investigation patterns",
  "calibrationUnavailable": "Calibration points unavailable; see the downloadable results.",
  "bestModel": "Highest mean PR-AUC",
  "resultTakeaway": "The network effect is a parameter of the simulator. The zero-effect condition tests whether graph features add value when outcomes do not depend on connections."
};
const spanish = {
  "skip": "Ir a la investigación",
  "headline": "Relaciones entre deudores",
  "intro": "Propiedad y garantías en un portafolio de créditos.",
  "fictional": "Datos sintéticos · MXN",
  "investigationTitle": "Propiedad y garantías",
  "choose": "Selecciona un patrón de relaciones.",
  "graphHint": "Selecciona una persona, empresa o crédito",
  "person": "Persona",
  "company": "Empresa",
  "loan": "Crédito",
  "observation": "Relación",
  "consequence": "Exposición",
  "review": "Aspectos por revisar",
  "notLoss": "Los saldos representan exposición conectada, no pérdidas estimadas. Los contratos determinan la responsabilidad.",
  "loansTitle": "Saldos de créditos",
  "dedup": "Cada crédito se cuenta una vez",
  "loansCaption": "Créditos afectados y motivo de revisión conjunta",
  "borrower": "Deudor",
  "relationship": "Conexión",
  "balance": "Saldo (MXN)",
  "relationshipsTitle": "Tabla de relaciones",
  "from": "Origen",
  "to": "Destino",
  "queryTitle": "Consulta Cypher",
  "queryNote": "Estas consultas ilustrativas usan un esquema en inglés, distinto al esquema histórico. SQL también puede recorrer relaciones de forma recursiva y detectar ciclos; la comparación es de claridad, no de una capacidad exclusiva.",
  "sqlDocs": "Documentación de consultas recursivas de PostgreSQL ↗",
  "evidenceTitle": "Evaluación de modelos",
  "modelIntro": "Compara modelos con atributos del deudor y de red bajo tres supuestos de dependencia.",
  "modelToggle": "Resultados y calibración",
  "modelLimits": "El modelo usa un conjunto sintético independiente. La evaluación utiliza grupos de deudores reservados; el desempeño en portafolios reales y periodos posteriores aún no se ha probado.",
  "methodTitle": "Datos y metodología",
  "demoMethodTitle": "Datos del portafolio",
  "demoMethod": "El portafolio contiene deudores, créditos y relaciones sintéticos. La exposición suma los saldos vigentes de créditos únicos; la responsabilidad de las garantías depende de los contratos.",
  "modelMethodTitle": "Datos de modelado",
  "modelMethod": "10.000 deudores en 1.000 grupos desconectados, con cinco semillas fijas. Se asignan grupos completos a entrenamiento (60 %), calibración (20 %) y prueba (20 %). Los predictores solo usan información disponible en la fecha de observación; los incumplimientos simulados ocurren en los 12 meses siguientes.",
  "evaluationTitle": "Protocolo de evaluación",
  "evaluation": "Se comparan una referencia constante, regresión logística con atributos del deudor y LightGBM con y sin atributos de red, tras calibración sigmoide. Se reportan PR-AUC, ROC-AUC, Brier y pérdida logarítmica con incertidumbre por remuestreo de grupos. La calibración nunca usa el conjunto de prueba.",
  "researchTitle": "Trabajo previo con datos públicos",
  "research": "El repositorio también contiene adquisición de datos públicos y cuadernos de investigación anteriores. Esos resultados históricos están separados de esta demostración ficticia y su experimento sintético. No se atribuyen dificultades financieras ficticias a empresas reales.",
  "downloadDemo": "Descargar datos del portafolio",
  "downloadModels": "Descargar resultados de modelos",
  "architectureTitle": "Implementación",
  "architecture": "Python genera el portafolio y los resultados como JSON versionado. D3 dibuja las relaciones. El repositorio incluye los datos, la configuración y los comandos de reproducción.",
  "source": "Código e instrucciones de reproducción",
  "github": "Código fuente",
  "loading": "Cargando evidencia…",
  "error": "No se pudieron cargar los datos. Abre esta página mediante HTTP y vuelve a intentar.",
  "retry": "Reintentar",
  "graphUnavailable": "Grafo no disponible. La tabla de relaciones contiene todas las conexiones.",
  "graphName": "Grafo dirigido de relaciones",
  "nodePrompt": "Selecciona un nodo para ver sus relaciones. Las flechas indican la dirección.",
  "exposure": "Saldo vigente · MXN",
  "loanCount": "Créditos",
  "borrowerCount": "Deudores",
  "owns": "es propietario de",
  "guarantees": "garantiza",
  "controls": "controla",
  "shareholder": "es accionista de",
  "borrows": "toma prestado",
  "issued_to": "otorgado a",
  "connections": "conexiones",
  "absent": "Sin efecto de red",
  "moderate": "Efecto de red moderado",
  "strong": "Efecto de red fuerte",
  "constant": "Referencia de tasa constante",
  "logistic_borrower": "Logística · solo deudor",
  "lightgbm_borrower": "LightGBM · solo deudor",
  "lightgbm_graph": "LightGBM · con red",
  "model": "Modelo",
  "metricNote": "Promedios de cinco semillas; intervalos del 95 % por remuestreo de grupos, condicionados a estas cinco ejecuciones ajustadas. No abarcan toda la incertidumbre del entrenamiento o del simulador. Mayor PR-AUC / ROC-AUC es mejor; menor Brier / pérdida logarítmica es mejor.",
  "average_precision": "PR-AUC (AP) ↑",
  "roc_auc": "ROC-AUC ↑",
  "brier": "Brier ↓",
  "log_loss": "Pérdida log. ↓",
  "calibration": "Calibración · primera semilla fija",
  "predicted": "Probabilidad predicha",
  "observed": "Tasa observada de incumplimiento",
  "ideal": "Calibración perfecta",
  "testCounts": "Positivos / deudores de prueba, por semilla",
  "missing": "No disponible",
  "uplift": "PR-AUC con red menos solo deudor",
  "scenarioGroup": "Patrones de investigación",
  "calibrationUnavailable": "Puntos de calibración no disponibles; consulta los resultados descargables.",
  "bestModel": "Mayor PR-AUC promedio",
  "resultTakeaway": "El efecto de red es un parámetro del simulador. La condición sin efecto evalúa si los atributos de red aportan valor cuando los resultados no dependen de las conexiones.",
  "navInvestigate": "Portafolio",
  "navEvidence": "Evaluación de modelos"
};
let language = 'en', demo = null, results = null, activeScenario = 'control';
english.networkIllustrationAlt = 'Paper buildings joined by fine threads, illustrating connections between borrowing companies.';
spanish.networkIllustrationAlt = 'Edificios de papel unidos por hilos que ilustran conexiones entre empresas deudoras.';
const states = {demo:'loading', model:'loading'};
english.navOverview = 'Introduction';
spanish.navOverview = 'Introducción';
english.readingGuide = 'Choose a relationship pattern below. Select a person, company, or loan in the diagram to see its connections; the table lists the balances behind the total.';
spanish.readingGuide = 'Elige un patrón de relaciones. Selecciona una persona, empresa o crédito en el diagrama para ver sus conexiones; la tabla muestra los saldos que componen el total.';
const t = key => (language === 'es' ? spanish : english)[key] || key;
const localized = value => typeof value === 'object' && value !== null ? value[language] || value.en || '' : String(value ?? '');
const number = value => new Intl.NumberFormat(language === 'es' ? 'es-MX' : 'en-US', {maximumFractionDigits:0}).format(value);
const metricNumber = value => Number.isFinite(value) ? value.toLocaleString(language === 'es' ? 'es-MX' : 'en-US', {minimumFractionDigits:3,maximumFractionDigits:3}) : t('missing');
function element(tag, text, className) { const el = document.createElement(tag); if(text !== undefined) el.textContent = text; if(className) el.className = className; return el; }
function setLanguage(lang) {
  language = lang; document.documentElement.lang = lang;
  try { localStorage.setItem('creditgraph-language', lang); } catch { /* Storage is optional. */ }
  document.querySelectorAll('a[href^="index.html"]').forEach(el => { el.setAttribute('href', 'index.html?lang=' + lang); });
  document.title = lang === 'es' ? 'CreditGraph · Exposición crediticia conectada' : 'CreditGraph · Connected credit exposure';
  document.querySelectorAll('[data-i18n]').forEach(el => {el.textContent = t(el.dataset.i18n);});
  document.querySelectorAll('[data-i18n-alt]').forEach(el => {el.alt = t(el.dataset.i18nAlt);});
  document.querySelectorAll('[data-lang]').forEach(el => el.setAttribute('aria-pressed', String(el.dataset.lang === lang)));
  $('scenarios').setAttribute('aria-label', t('scenarioGroup'));
  renderStatus('demo'); renderStatus('model');
  if(demo) renderDemo(); if(results) renderModels();
}
function renderStatus(kind) {
  const el = $(kind + '-status'); el.replaceChildren();
  if(states[kind] === 'ready') return;
  el.append(element('span', t(states[kind] === 'error' ? 'error' : 'loading')));
  if(states[kind] === 'error') { const button = element('button', t('retry'), 'retry'); button.type='button'; button.onclick=()=>load(kind); el.append(button); }
}
async function load(kind) {
  states[kind]='loading'; renderStatus(kind);
  try {
    const response = await fetch(kind === 'demo' ? 'data/demo.json' : 'data/model-results.json');
    if(!response.ok) throw new Error('HTTP ' + response.status);
    const data = await response.json();
    if(kind === 'demo') { validateDemo(data); demo=data; renderDemo(); $('demo-content').hidden=false; }
    else { if(!Array.isArray(data.summary) || !data.summary.length || !Array.isArray(data.runs)) throw new Error('Invalid model data'); results=data; renderModels(); }
    states[kind]='ready';
  } catch(error) { states[kind]='error'; if(kind==='demo') {demo=null; $('demo-content').hidden=true;} else {results=null; $('model-content').replaceChildren();} console.error(kind + ' load failed',error); }
  renderStatus(kind);
}
function validateDemo(data) {
  if(!Array.isArray(data.scenarios) || !data.scenarios.length) throw new Error('Missing scenarios');
  for(const s of data.scenarios) {
    if(!s.id || !s.title || !Array.isArray(s.nodes) || !Array.isArray(s.edges) || !Array.isArray(s.loans) || !s.metrics) throw new Error('Invalid scenario');
    const nodes=new Set(s.nodes.map(n=>n.id)); const loans=new Map(s.loans.map(l=>[l.id,l]));
    if(loans.size!==s.loans.length || s.loans.some(l=>!Number.isFinite(l.amount_mxn) || l.amount_mxn<0) || s.edges.some(e=>!nodes.has(e.source)||!nodes.has(e.target))) throw new Error('Invalid relationships or balances');
    const total=[...loans.values()].reduce((sum,l)=>sum+l.amount_mxn,0);
    if(total!==s.metrics.exposure_mxn || loans.size!==s.metrics.loan_count || !Number.isFinite(s.metrics.borrower_count)) throw new Error('Inconsistent exposure');
  }
}
function renderDemo() {
  const scenario = demo.scenarios.find(s=>s.id===activeScenario) || demo.scenarios[0]; activeScenario=scenario.id;
  const existing = new Map([...$('scenarios').children].map(el=>[el.dataset.scenario,el]));
  demo.scenarios.forEach(s=>{let button=existing.get(s.id); if(!button) {button=element('button');button.type='button';button.dataset.scenario=s.id;button.onclick=()=>{activeScenario=s.id;renderDemo();};$('scenarios').append(button);} button.textContent=localized(s.title);button.setAttribute('aria-pressed',String(s.id===activeScenario));});
  $('scenario-title').textContent=localized(scenario.title);
  ['observation','consequence','review'].forEach(key=>$(key).textContent=localized(scenario[key]));
  $('query').textContent=scenario.query;
  $('metrics').replaceChildren(...[['exposure_mxn','exposure'],['loan_count','loanCount'],['borrower_count','borrowerCount']].map(([key,label])=>{const box=element('div',undefined,'metric');box.append(element('div',number(scenario.metrics[key]),'metric-value'),element('div',t(label),'metric-label'));return box;}));
  $('loan-rows').replaceChildren(...scenario.loans.map(loan=>{const row=element('tr');row.dataset.loan=loan.id;row.dataset.borrower=loan.borrower_id || loan.borrower;[loan.id,loan.borrower,localized(loan.relationship),number(loan.amount_mxn)].forEach((value,index)=>row.append(element('td',value,index===3?'numeric':undefined)));return row;}));
  const names=new Map(scenario.nodes.map(n=>[n.id,localized(n.label)]));
  $('relationship-rows').replaceChildren(...scenario.edges.map(edge=>{const row=element('tr');[names.get(edge.source),t(edge.type),names.get(edge.target)].forEach(value=>row.append(element('td',value)));return row;}));
  drawGraph(scenario);
}
function drawGraph(scenario) {
  $('graph').replaceChildren(); $('node-detail').textContent=t('nodePrompt');
  if(!window.d3) { $('graph').append(element('p',t('graphUnavailable'),'notice'));return; }
  const width=Math.max(288,Math.min(620,$('graph').clientWidth - 20)),height=scenario.id==='hub'?430:355,colors={person:'#b3c6e5',company:'#d6ed80',loan:'#7ac9ba'};
  const edgeStyles = {owns:{color:'#7ac9ba',dash:''}, shareholder:{color:'#d6ed80',dash:'7 4'}, guarantees:{color:'#b3c6e5',dash:'2 5'}};
  const nodes=scenario.nodes.map(n=>({...n}));
  const tiers=['person','company','loan'].map(type=>nodes.filter(n=>n.type===type));
  tiers.forEach((tier,index)=>tier.forEach((node,i)=>{node.x=(i+1)*width/(tier.length+1);node.y=55+index*108;}));
  if(scenario.id==='hub') tiers.forEach((tier,index)=>tier.forEach(node=>{node.y=65+index*150;}));
  // Alternating people and their guaranteed loans exposes the cycle without crossed edges.
  if(scenario.id==='cycle' && tiers[0].length===3 && tiers[2].length===3) {
    const ring=[tiers[0][0],tiers[2][1],tiers[0][1],tiers[2][2],tiers[0][2],tiers[2][0]];
    ring.forEach((node,i)=>{const angle=(-150+i*60)*Math.PI/180;node.x=width/2+(width/2-48)*Math.cos(angle);node.y=155+110*Math.sin(angle);});
  }
  const positions=new Map(nodes.map(n=>[n.id,n]));
  const svg=d3.select('#graph').append('svg').attr('viewBox',`0 0 ${width} ${height}`).attr('role','group').attr('aria-label',t('graphName'));
  svg.append('title').text(localized(scenario.title));
  svg.append('defs').append('marker').attr('id','arrow').attr('viewBox','0 -4 8 8').attr('refX',7).attr('refY',0).attr('markerWidth',6).attr('markerHeight',6).attr('orient','auto').append('path').attr('d','M0,-4L8,0L0,4').attr('fill','#779aa7');
  scenario.edges.forEach((edge,index)=>{
    const a=positions.get(edge.source),b=positions.get(edge.target),dx=b.x-a.x,dy=b.y-a.y,distance=Math.hypot(dx,dy)||1;
    const x1=a.x+dx/distance*20,y1=a.y+dy/distance*20,x2=b.x-dx/distance*25,y2=b.y-dy/distance*25;
    const sameTier=a.type===b.type;const reverse=scenario.edges.some(e=>e.source===edge.target&&e.target===edge.source);
    const bend=sameTier?(reverse?(dx>0?-38:38):-32):0;
    const mx=(x1+x2)/2,my=(y1+y2)/2+bend;
    const style=edgeStyles[edge.type] || edgeStyles.owns;
    svg.append('path').datum(edge).attr('class','graph-edge').attr('d',`M${x1},${y1} Q${mx},${my} ${x2},${y2}`).style('stroke',style.color).attr('stroke-dasharray',style.dash).attr('marker-end','url(#arrow)').append('title').text(`${localized(a.label)} ${t(edge.type)} ${localized(b.label)}`);
  });
  function selectNode(node) {
    svg.selectAll('.node').classed('selected',n=>n.id===node.id).attr('aria-pressed',n=>String(n.id===node.id));
    svg.selectAll('.graph-edge').style('opacity',e=>e.source===node.id||e.target===node.id?1:0.18);
    const edges=scenario.edges.filter(e=>e.source===node.id||e.target===node.id);
    $('node-detail').textContent=`${localized(node.label)} · ${t(node.type)} · ${edges.length} ${t('connections')}. `+edges.map(e=>`${localized(positions.get(e.source).label)} ${t(e.type)} ${localized(positions.get(e.target).label)}`).join('; ');
    $('loan-rows').querySelectorAll('tr').forEach(row=>row.classList.toggle('selected',row.dataset.loan===node.id||row.dataset.borrower===node.id));
  }
  const groups=svg.selectAll('.node').data(nodes).join('g').attr('class','node').attr('transform',n=>`translate(${n.x},${n.y})`).attr('role','button').attr('tabindex',0).attr('aria-label',n=>`${localized(n.label)}, ${t(n.type)}`).attr('aria-pressed','false').on('click',(_,n)=>selectNode(n)).on('keydown',(event,n)=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectNode(n);}});
  groups.each(function(n){const group=d3.select(this); if(n.type==='loan')group.append('rect').attr('x',-16).attr('y',-16).attr('width',32).attr('height',32).attr('rx',5).attr('fill','#193c3a').attr('stroke',colors[n.type]);else group.append('circle').attr('r',18).attr('fill',n.type==='person'?'#243446':'#333e27').attr('stroke',colors[n.type]);group.append('text').attr('text-anchor','middle').attr('y',4).attr('fill',colors[n.type]).style('font-size','11px').text(n.type==='person'?'P':n.type==='loan'?'$':'C');});
  // Place names in free space, measured using the actual font, not fixed estimates.
  const occupied=nodes.map(n=>({x:n.x-22,y:n.y-22,width:44,height:44}));
  const samples=[];
  svg.selectAll('.graph-edge').each(function(){
    const length=this.getTotalLength();
    for(let at=0;at<=length;at+=2) samples.push(this.getPointAtLength(at));
  });
  const intersects=(a,b)=>a.x<b.x+b.width && a.x+a.width>b.x && a.y<b.y+b.height && a.y+a.height>b.y;
  groups.each(function(n){
    const label=d3.select(this).append('text').attr('class','node-name').attr('text-anchor','middle').text(localized(n.label));
    const offsets=[...(n.type==='loan'?[[0,39],[0,-30]]:[[0,-30],[0,39]]),[-30,4],[30,4],[0,-46],[0,55],[-30,-27],[30,-27],[-30,39],[30,39]];
    let chosen=null;
    for(const [dx,dy] of offsets){
      label.attr('x',dx).attr('y',dy).attr('text-anchor',dx<0?'end':dx>0?'start':'middle');
      const box=label.node().getBBox();
      const bounds={x:n.x+box.x-4,y:n.y+box.y-3,width:box.width+8,height:box.height+6};
      if(bounds.x<4 || bounds.y<4 || bounds.x+bounds.width>width-4 || bounds.y+bounds.height>height-4 || occupied.some(other=>intersects(bounds,other))) continue;
      const collisions=samples.filter(p=>p.x>bounds.x && p.x<bounds.x+bounds.width && p.y>bounds.y && p.y<bounds.y+bounds.height).length;
      if(!chosen || collisions<chosen.collisions) chosen={dx,dy,bounds,collisions};
      if(collisions===0) break;
    }
    if(chosen){
      label.attr('x',chosen.dx).attr('y',chosen.dy).attr('text-anchor',chosen.dx<0?'end':chosen.dx>0?'start':'middle');
      occupied.push(chosen.bounds);
    }
  });
  const legend=element('div',undefined,'legend relationship-legend');
  [...new Set(scenario.edges.map(edge=>edge.type))].forEach(type=>{
    const item=element('span'),swatch=document.createElementNS('http://www.w3.org/2000/svg','svg');
    swatch.setAttribute('viewBox','0 0 32 12');swatch.setAttribute('aria-hidden','true');
    const line=document.createElementNS(swatch.namespaceURI,'line');
    const style=edgeStyles[type] || edgeStyles.owns;
    Object.entries({x1:1,y1:6,x2:31,y2:6,stroke:style.color,'stroke-width':2,'stroke-dasharray':style.dash}).forEach(([key,value])=>line.setAttribute(key,value));
    swatch.append(line);item.append(swatch,element('span',t(type)));legend.append(item);
  });
  $('graph').append(legend);
}
function renderModels() {
  const container=$('model-content');container.replaceChildren(element('p',t('metricNote'),'model-meta'));
  const keys=['average_precision','roc_auc','brier','log_loss'];
  results.summary.forEach(condition=>{
    const section=element('section',undefined,'model-condition');section.append(element('h3',t(condition.condition)));
    const ranked=condition.models.filter(model=>Number.isFinite(model.metrics?.average_precision?.mean)).slice().sort((a,b)=>b.metrics.average_precision.mean-a.metrics.average_precision.mean);
    if(ranked.length)section.append(element('p',`${t('bestModel')}: ${t(ranked[0].name)} (${metricNumber(ranked[0].metrics.average_precision.mean)})`,'model-meta'));
    const scroll=element('div',undefined,'table-scroll'),table=element('table'),head=element('thead'),hr=element('tr');
    hr.append(element('th',t('model')),...keys.map(key=>element('th',t(key),'numeric')));head.append(hr);table.append(head);
    const body=element('tbody');condition.models.forEach(model=>{const row=element('tr');row.append(element('td',t(model.name)));keys.forEach(key=>{const value=model.metrics[key];const cell=element('td',metricNumber(value?.mean),'numeric');if(Array.isArray(value?.ci95))cell.append(element('span',`[${metricNumber(value.ci95[0])}, ${metricNumber(value.ci95[1])}]`,'interval'));row.append(cell);});body.append(row);});table.append(body);scroll.append(table);section.append(scroll);
    const uplift=condition.graph_uplift?.average_precision;
    if(uplift)section.append(element('p',`${t('uplift')}: ${metricNumber(uplift.mean)} [${metricNumber(uplift.ci95?.[0])}, ${metricNumber(uplift.ci95?.[1])}]`,'model-meta'));
    const runs=results.runs.filter(run=>run.condition===condition.condition);
    const counts=runs.map(run=>{const count=run.split_counts?.test;return count ? `${run.seed}: ${count.positives ?? count.n_positives ?? '—'}/${count.borrowers ?? count.n ?? count.rows ?? '—'}` : null;}).filter(Boolean);
    if(counts.length)section.append(element('p',t('testCounts')+' · '+counts.join(' · '),'model-meta'));
    if(runs.length)drawCalibration(section,runs[0]);container.append(section);
  });
}
function drawCalibration(parent,run) {
  const wrapper=element('div',undefined,'model-chart');wrapper.append(element('h4',t('calibration')+` (${run.seed})`));parent.append(wrapper);
  if(!window.d3){wrapper.append(element('p',t('calibrationUnavailable')));return;}
  const colors=['#b0bec5','#b3c6e5','#7ac9ba','#d6ed80'];
  const curves=run.models.map((m,index)=>({name:m.name,color:colors[index],points:(m.calibration_curve?.predicted || []).map((x,i)=>({x,y:m.calibration_curve.observed[i]})).filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y))}));
  if(!curves.some(c=>c.points.length)){wrapper.append(element('p',t('calibrationUnavailable')));return;}
  const width=Math.max(300,Math.min(620,$('model-content').clientWidth || window.innerWidth-80)),height=280,margin={left:55,right:20,top:15,bottom:42},x=d3.scaleLinear().domain([0,1]).range([margin.left,width-margin.right]),y=d3.scaleLinear().domain([0,1]).range([height-margin.bottom,margin.top]);
  const svg=d3.select(wrapper).append('svg').attr('viewBox',`0 0 ${width} ${height}`).attr('role','img').attr('aria-label',`${t('calibration')}. ${t('predicted')}; ${t('observed')}.`);
  svg.append('line').attr('x1',x(0)).attr('y1',y(0)).attr('x2',x(1)).attr('y2',y(1)).attr('stroke','#7597a2').attr('stroke-dasharray','4 5');
  svg.append('g').attr('transform',`translate(0,${y(0)})`).call(d3.axisBottom(x).ticks(5).tickFormat(d3.format('.0%')));
  svg.append('g').attr('transform',`translate(${x(0)},0)`).call(d3.axisLeft(y).ticks(5).tickFormat(d3.format('.0%')));
  svg.append('text').attr('x',width/2).attr('y',height-5).attr('text-anchor','middle').attr('fill','#a1b8c1').attr('font-size',10).text(t('predicted'));
  svg.append('text').attr('transform','rotate(-90)').attr('x',-height/2).attr('y',13).attr('text-anchor','middle').attr('fill','#a1b8c1').attr('font-size',10).text(t('observed'));
  const legend=element('div',undefined,'legend');
  curves.forEach(curve=>{svg.append('path').datum(curve.points).attr('d',d3.line().x(p=>x(p.x)).y(p=>y(p.y))).attr('fill','none').attr('stroke',curve.color).attr('stroke-width',2);svg.selectAll(null).data(curve.points).enter().append('circle').attr('cx',p=>x(p.x)).attr('cy',p=>y(p.y)).attr('r',3).attr('fill',curve.color).append('title').text(p=>`${t(curve.name)}: ${t('predicted')} ${metricNumber(p.x)}, ${t('observed')} ${metricNumber(p.y)}`);const item=element('span',t(curve.name));item.style.color=curve.color;legend.append(item);});wrapper.append(legend);
}
document.querySelectorAll('[data-lang]').forEach(button=>button.addEventListener('click',()=>setLanguage(button.dataset.lang)));
let preferredLanguage = new URLSearchParams(location.search).get('lang');
if (!preferredLanguage) { try { preferredLanguage = localStorage.getItem('creditgraph-language'); } catch { /* Default English. */ } }
setLanguage(preferredLanguage === 'es' ? 'es' : 'en');
function revealSection() {
  const id = location.hash.slice(1);
  if (id === 'evidence') $('model-details').open = true;
  if (id === 'methodology') $('methodology').open = true;
  if (['investigation', 'evidence', 'methodology'].includes(id)) {
    requestAnimationFrame(() => $(id).scrollIntoView());
  }
}
window.addEventListener('hashchange', revealSection);
Promise.allSettled([load('demo'),load('model')]).then(revealSection);
document.fonts?.ready.then(()=>{
  const scenario=demo?.scenarios.find(s=>s.id===activeScenario);
  if(scenario) drawGraph(scenario);
});
let graphWidth=0;
if(window.ResizeObserver) new ResizeObserver(entries=>{
  const width=Math.round(entries[0].contentRect.width);
  if(width && width!==graphWidth) {graphWidth=width;const scenario=demo?.scenarios.find(s=>s.id===activeScenario);if(scenario)drawGraph(scenario);}
}).observe($('graph'));
let modelWidth=0;
if(window.ResizeObserver) new ResizeObserver(entries=>{
  const width=Math.round(entries[0].contentRect.width);
  if(width && width!==modelWidth) {modelWidth=width;if(results)renderModels();}
}).observe($('model-content'));
