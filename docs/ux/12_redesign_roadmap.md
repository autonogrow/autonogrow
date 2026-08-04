# 12 — Roadmap de rediseño

## Secuencia

Cada bloque debe ser un diff pequeño, reversible y verificable. Ninguno autoriza un cambio de endpoint, permiso o modelo. Si una vista necesita API nueva —por ejemplo Auditoría Owner transversal— se diseña y aprueba como dependencia separada.

| Sprint | Objetivo | Archivos probables | Riesgos/dependencias | Criterios de aceptación y pruebas | Tamaño |
|---|---|---|---|---|---|
| **5A.2 Sistema visual y shell responsive** | tokens, tipografía, foco, shell y primitivas aditivas | `autonogrow-shared/*`, HTML/CSS de apps | contraste de colores configurables; clases legacy; carga de fuentes/CSP | cero contratos rotos; visual regression 5 anchos; teclado; contraste AA; seis temas intactos | Grande |
| **5B.1 Dashboard Business Admin** | Inicio centrado en hoy, mensajes y alertas | Admin index/styles/admin.js, quizá módulos nuevos | métricas derivadas/polling; acceso personal | datos actuales sin nuevas autorizaciones; estados carga/vacío/error; 360–1440; pruebas de resumen/roles | Medio |
| **5B.2 Agenda y reservas** | Agenda Hoy/semana/pendientes y detalle accionable; reagenda accesible | Admin bookings module/HTML/CSS | status/outbox, deep link `booking`, slots públicos, borradores | confirmar/reagendar/completar/cancelar; foco diálogo; conflictos; adjuntos/notas; staff-only | Grande |
| **5B.3 Conversaciones** | bandeja enfocada y configuración secundaria | Admin conversations/outbox/templates/automation | refrescos, suggestions, entrega integrada/asistida, handlers inline | filtros/hilo/compose/sugerencias/pausa; estados de entrega; móvil y teclado; no XSS en fixtures | Grande |
| **5B.4 Configuración del negocio** | hub Más: servicios, equipo, horarios y web | Admin HTML/CSS + módulos domain | formularios dinámicos, media, borrado staff, hash legacy | CRUD completo, dirty-state, medios, excepciones, modal bloqueo, redirects de hashes | Grande |
| **5B.5 Canales y automatizaciones** | stepper comprensible de canal y compuertas | Admin channels/automation + shared state components | OAuth/SDK Meta, candidaturas, health async, créditos | Instagram/WhatsApp happy/cancel/error/reconnect; approval ≠ delivery ≠ automation; no secretos DOM/log | Grande |
| **5C.1 Dashboard Owner** | resumen por decisiones y excepciones | Owner index/styles/owner.js o módulos | agregados disponibles; no provocar N×cargas | approvals/health/incidents visibles o enlazados; carga parcial honesta; 10+ negocios | Medio |
| **5C.2 Negocios y aprobaciones** | lista compacta, ficha y cola transversal | Owner businesses/approvals/onboarding | endpoints existentes están por negocio; URL/deep links; roles | buscar/filtrar/abrir; aprobar/rechazar con motivo; business isolation; candidatura expirada | Grande |
| **5C.3 Integraciones e incidencias** | vista por capa, reconexión y operación orientada a impacto | Owner integrations/incidents/operations | códigos técnicos, async jobs, acciones destructivas | matriz de estados; diálogo impacto/motivo; health/retry/reconnect; IDs en avanzado; audit ref | Grande |
| **5D.1 Onboarding** | alta mínima + checklist y revisión | Owner onboarding HTML/JS/CSS; shared stepper/forms | estado de 15 pasos, plantillas, readiness version, activación | reanudar/saltar opcional/preview/activar; no pérdida; bloqueo obsoleto; teclado/móvil | Grande |
| **5E.1 Landings** | estructura común accesible, temas por tokens y reserva progresiva | Landing HTML/CSS/script, assets; shared primitives selectivas | SEO, colores personalizados, media, conflicto de slots, demos | seis temas; reserva completa; sin disponibilidad; attachments partial success; Lighthouse/axe/visual | Grande |
| **5F.1 Responsive y accesibilidad** | cerrar auditoría WCAG 2.2 AA inicial y regresiones | todas las apps/tests/docs | no es solo CSS; lectores/patrones de foco | matriz 360/390/768/1024/1440; zoom 400; teclado; NVDA/VoiceOver; axe + revisión manual | Grande |
| **5G.1 Validación con piloto** | validar comprensión/tiempo/errores con negocios reales | documentación, analítica consentida, cambios pequeños resultantes | muestra sesgada, privacidad, no confundir opinión con uso | tareas definidas, baseline, 5–8 sesiones iniciales, hallazgos priorizados, go/no-go | Medio |

## Detalle de pruebas mínimas

### Automatizadas

- Tests existentes de backend para contratos afectados, aunque un sprint visual no debe alterar schemas.
- Tests DOM ligeros o Playwright cuando se incorpore: navegación/hash, modal/foco, reserva, conversación y Owner decision.
- Axe como detector, nunca como certificación.
- Capturas por app/viewport/tema con datos deterministas.
- Test de interpolación con `<`, comillas, URLs largas y mensajes backend seguros.

### Manuales

- Roles Owner, Admin, staff y customer; 401/403 y negocio equivocado.
- Éxito, vacío, error, carga lenta, mutación correcta + refresco fallido.
- Teclado, lector, zoom, touch y reduced motion.
- OAuth/Embedded: cancel, timeout, candidatura, expirada, retry, approve/reject y reconnect.
- Entrega integrada vs asistida; automatización sin capacidad/créditos.

## Orden razonado

El shell/tokens va primero porque reduce divergencia, pero debe ser aditivo. Agenda y conversaciones siguen por frecuencia del piloto. Owner se aborda después de contar con primitivas de lista, badge, feedback y diálogo. Onboarding y Landing se cambian cuando los componentes base y la operación diaria ya están validados. Accesibilidad se prueba en cada sprint; 5F.1 es cierre transversal, no aplazamiento.

## Métricas de éxito

- Tiempo para localizar/confirmar una cita pendiente.
- Tiempo para responder un mensaje nuevo.
- Porcentaje de altas que llegan a readiness sin soporte.
- Tiempo desde candidatura hasta decisión Owner.
- Reconexiones completadas sin intervención técnica manual.
- Errores/reintentos por flujo y tareas abandonadas.
- Éxito de tareas a 390 px y solo teclado.

No usar métricas de clic aisladas para justificar más elementos visibles. Medir resultado, error y necesidad de ayuda.

## Riesgos globales

1. “Reordenar” DOM puede romper listeners relativos aunque IDs sobrevivan.
2. Compartir CSS demasiado pronto puede crear colisiones `.active`, `.card`, `.button` y temas.
3. Un dashboard agregado puede demandar endpoints nuevos; evitar recrear N llamadas invisibles.
4. Simplificar textos no debe ocultar causas necesarias para Owner/soporte.
5. La nueva IA podría sugerir que un toggle único controla todas las capas Meta; mantener controles separados.
6. Sin pruebas con datos largos y estados fallidos, una visual regression de happy path es insuficiente.

## Mensaje de commit propuesto para este sprint

```text
docs(ux): auditar frontend y definir arquitectura de rediseño
```

No realizar commit hasta aprobación expresa.

