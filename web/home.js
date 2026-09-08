'use strict';

const homeEnglish = Object.fromEntries([...document.querySelectorAll('[data-i18n]')].map(el => [el.dataset.i18n, el.textContent]));
homeEnglish.imageAlt = 'Paper buildings connected by threads.';
const homeSpanish = {
  skip: 'Ir a la introducción', portfolio: 'Portafolio', models: 'Evaluación de modelos',
  title: 'Cuando los deudores están conectados, sus riesgos también pueden estarlo.',
  lead: 'Un banco puede prestar a varias empresas sin ver que comparten un propietario, o que una ha prometido pagar el crédito de otra.',
  description: 'CreditGraph reúne esas relaciones en una misma vista. Puedes ver qué deudores están vinculados, cuánto deben y qué conviene revisar.',
  start: 'Empezar con la propiedad compartida', startNote: 'El primer ejemplo reúne tres empresas y un propietario.',
  imageAlt: 'Edificios de papel conectados por hilos.',
  contextTitle: '¿Por qué revisar los créditos juntos?',
  contextOne: 'Imagina tres empresas que reciben créditos del mismo banco. Cada una tiene su propio crédito, pero las tres dependen de un propietario. Contarlas como deudores separados puede ocultar esa dependencia común.',
  contextTwo: 'Un analista puede revisar el saldo conjunto y preguntar cuánto dependen las empresas de esa persona. La conexión le da un motivo para investigar.',
  exampleLink: 'Ver las empresas y sus créditos →', guideTitle: 'Algunos términos para empezar',
  borrowerTerm: 'Deudor', borrowerDefinition: 'Persona o empresa que debe dinero por un crédito.',
  guaranteeTerm: 'Garantía', guaranteeDefinition: 'Promesa de cubrir el crédito de otro deudor, según lo establecido en el contrato.',
  exposureTerm: 'Exposición conectada', exposureDefinition: 'Los saldos pendientes de los créditos del grupo que estás revisando.',
  researchTitle: '¿Conocer las relaciones mejora las predicciones?',
  researchText: 'Un experimento independiente compara modelos con y sin datos de relaciones. Los resultados muestran cómo cambia su desempeño bajo distintos supuestos de red.',
  researchLink: 'Leer los resultados de los modelos →', methodology: 'Datos y metodología', source: 'Código fuente'
};
function homeLanguage(lang) {
  const dictionary = lang === 'es' ? homeSpanish : homeEnglish;
  document.documentElement.lang = lang;
  document.title = lang === 'es' ? 'CreditGraph · Relaciones entre deudores' : 'CreditGraph · Understanding connected borrowers';
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = dictionary[el.dataset.i18n]; });
  document.querySelectorAll('[data-i18n-alt]').forEach(el => { el.alt = dictionary[el.dataset.i18nAlt]; });
  document.querySelectorAll('[data-lang]').forEach(el => el.setAttribute('aria-pressed', String(el.dataset.lang === lang)));
  document.querySelectorAll('[data-analysis-link]').forEach(el => {
    const url = new URL(el.href); url.searchParams.set('lang', lang); el.href = url.href;
  });
  try { localStorage.setItem('creditgraph-language', lang); } catch { /* Storage is optional. */ }
}
let preferredLanguage = new URLSearchParams(location.search).get('lang');
if (!preferredLanguage) { try { preferredLanguage = localStorage.getItem('creditgraph-language'); } catch { /* Default English. */ } }
homeLanguage(preferredLanguage === 'es' ? 'es' : 'en');
document.querySelectorAll('[data-lang]').forEach(el => el.addEventListener('click', () => homeLanguage(el.dataset.lang)));
// Preserve previously shared links to the portfolio and model sections.
if (['#investigation', '#evidence', '#methodology'].includes(location.hash)) {
  location.replace('analysis.html?lang=' + document.documentElement.lang + location.hash);
}
