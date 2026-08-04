# 04 — Contratos DOM que debe preservar el rediseño

## Criterio

- **Crítico**: participa en eventos, carga/mutación, navegación, autorización visible o procesos de negocio.
- **Importante**: recibe render dinámico, comunica estado o enlaza dos vistas; cambiarlo exige revisar JS/CSS.
- **Solo visual**: el JavaScript no depende de él, aunque CSS sí puede hacerlo.
- **Aparentemente sin uso**: no aparece literalmente fuera del HTML en una búsqueda estática. No autoriza borrado: puede ser objetivo de fragmentos, selectores construidos o pruebas.

Regla de migración: no renombrar un contrato crítico o importante sin buscar todas sus apariciones, actualizar listener/render/prueba y verificar el flujo completo. Conservar además orden relativo cuando el JS usa `closest`, `querySelector` dentro de un panel o `insertBefore`.

## Contratos transversales críticos

| Contrato | Consumidor/garantía |
|---|---|
| `window.AutonoGrowAuth` y sus métodos | Todos los frontends; sesión, CSRF y logout |
| `?b=<slug>` | Admin/Landing y enlaces Owner; contexto del negocio |
| hash Admin (`#summary`, `#bookings`, etc.) | `showAdminSection`, deep links y vuelta desde Owner |
| `.active`, `[hidden]`, `.open` | mecanismos actuales de visibilidad; no sustituir solo con estilo |
| `data-*` con IDs | delegación de eventos; el valor se envía al endpoint correspondiente |
| `button[type=button]` frente a submit | evita envíos accidentales en paneles generados |
| carga de `auth.js` antes del script de app | cada wrapper accede a `AutonoGrowAuth` al inicializar |

## Admin

### Navegación, sesión y shell

Críticos: `#admin-login`, `#admin-content`, `#admin-login-message`, `#google-signin-button`, `#logout-button`, `#refresh-button`, `#business-title`, `#business-subtitle`, `#public-page-link`, `#sync-status`, `.admin-tab[data-section]`, `.admin-section`, `.admin-tab-active`, `.admin-section-active`, `data-conversation-admin-only`. `showAdminSection()` también es global porque existe `onclick` inline.

Secciones críticas por hash/selector: `#summary`, `#growth`, `#bookings`, `#conversations`, `#messages`, `#services`, `#staff`, `#schedule`, `#channels`, `#business`, `#reviews`.

### Resumen y crecimiento

Importantes: IDs de métricas de reservas, mensajes, servicios/personal/reseñas; `#growth-task-list`, `#growth-progress-label`, `.growth-progress[role=progressbar]` y su span, `[data-growth-task]`. `renderGrowth()` actualiza `aria-valuenow`; conservar el elemento semántico, no solo la barra visual.

### Reservas y reseñas

| Criticidad | Contratos |
|---|---|
| Crítico | `#bookings-list`, `#booking-staff-filter`, `[data-booking-view]`, `[data-internal-notes]`, IDs/acciones generadas con booking ID, `#reschedule-modal`, `#reschedule-modal-title`, `#reschedule-modal-content`, controles generados del modal |
| Crítico | `#staff-removal-modal`, `#staff-removal-modal-title`, `#staff-removal-modal-message`, lista de reservas bloqueantes |
| Importante | contadores/filtros de booking, empty/loading cards, `#review-requests-list`, historial y métricas, `[data-review-feedback]`, `[data-review-fallback]` |
| Estructural | una tarjeta debe conservar el booking ID accesible al listener; el modal necesita permanecer fuera del contenido que se rerenderiza |

El parámetro URL `booking=<id>` abre una reserva concreta. Los callbacks inline de estado, reseña, conversación y plantilla exigen que sus funciones sigan disponibles en `window` hasta retirar el inline handler de forma controlada.

### Servicios, personal y horarios

- Críticos de servicios: `#services-list`, inputs `#new-service-*`, `#services-feedback`, `[data-service-id]` y clases internas consultadas por cada tarjeta.
- Críticos de personal: `#staff-list`, creación, `[data-staff-id]`, `[data-inactive-staff-id]`, checkboxes de servicios, selectores de disponibilidad y feedback por miembro.
- Críticos de horarios: `#weekly-schedule-editor`, `#availability-feedback`, `[data-weekday]`, `#availability-exceptions-list`, campos `#exception-*`, borrado por ID y panel de ventanas.
- Importantes: `#inactive-staff-section`; no aparece literalmente en JS/CSS y hoy actúa como agrupador semántico, por lo que debe verificarse antes de cambiar.

### Conversaciones y outbox

| Área | Contratos críticos/importantes |
|---|---|
| Lista/filtros | formulario/filtros `conversation-*`, `#conversation-list`, conversación seleccionada global, IDs generados |
| Hilo | `#conversation-detail`, thread/messages, compose, feedback, `[data-last-message-id]` |
| Sugerencias | suggestion ID y acciones generadas; selección global |
| Plantillas | `#conversation-template-list`, `[data-conversation-template-id]`, `.conversation-template-item-*` |
| Automatización | `#conversation-automation-content`, IDs `conversation-automation-*`, `[data-automation-intent]`, clases de rule |
| Mensajes automáticos | `#message-outbox-list`, historial, filtros, `[data-message-count]`; IDs de contadores reciben actualización indirecta por `data-*` |

`#conversation-templates-panel` y `#conversation-automation-panel` no se encuentran literalmente en JS/CSS, pero contienen controles críticos; clasificarlos como agrupadores importantes, no “muertos”. Los contadores `#message-count-*` se actualizan mediante `[data-message-count]` y son un ejemplo de por qué una búsqueda literal de IDs no basta.

### Canales y marca

- Críticos: `#channel-onboarding-list`, `#channel-onboarding-feedback`, `[data-channel-request]`, `[data-channel-health-action]`, `[data-channel]`, `[data-meta-embedded-signup]`.
- Críticos: settings inputs, select de tema/plantilla, `#admin-logo-input`, `#admin-gallery-*`, `[data-toggle-image]`, `[data-delete-image]`, `[data-alt-id]`, `[data-position-id]`.
- Los IDs `business-setting-*-color` se acceden con nombres construidos; son críticos aunque no aparezcan como literal completo en el análisis estático.
- `sessionStorage.adminMediaPending` es parte del contrato de recuperación de subida; no cambiar la key sin migración compatible.

## Owner

### Shell y paneles

Críticos: `#owner-login`, `#owner-content`, mensajes/botones auth, `[data-tab]`, `[data-panel]`, `#business-list`, `#new-business-panel`, `#incidents-panel`, `#queues-panel`, `#operations-panel`. `setActiveTab()` depende de los valores exactos `businesses`, `new-business`, `incidents`, `queues`, `operations`.

`#businesses-section` y `#onboarding-wizard` no aparecen literalmente en JS/CSS; son agrupadores aparentemente sin uso directo, pero no deben eliminarse sin comprobación de tests/semántica.

### Tarjeta de negocio generada

El contrato no es solo un ID: listeners delegados usan la relación `button.closest(panel)` y búsquedas locales. Son críticos:

- `[data-business-state-id]`, `[data-business-status]`, `[data-owner-editor]`, `[data-slug]`;
- marca: `[data-owner-brand-save]`, `[data-owner-color]`, `[data-owner-hex]`, `[data-owner-template]`, `[data-owner-theme]`, `[data-owner-media-input]`, `[data-owner-gallery]`, atributos de imagen;
- usuarios: `[data-owner-users-id]`, `[data-owner-user-action]`, `[data-business-user-id]`, `[data-membership-role]`, email/role/list/feedback;
- canales: `[data-owner-channel-control-id]`, content/feedback, `[data-owner-channel-action]`, `[data-channel]`, delivery/automation/policy y `[data-attempt-id]`;
- Instagram: `[data-owner-integration-id]`, nombre/content/feedback/form/reconnect, acciones, account/token/expiration/reason y OAuth purpose;
- automatización: `[data-owner-automation-id]`, nombre/content/feedback y todos los atributos `data-owner-automation-*`, crédito/plan/límite/historial.

Mover un botón fuera de su tarjeta rompe el `closest()` aunque se conserve el atributo. Duplicar una tarjeta con el mismo identificador puede dirigir una acción al negocio equivocado.

### Onboarding

Críticos: `#onboarding-start`, `#onboarding-workspace`, `#onboarding-template`, `#onboarding-name`, `#onboarding-slug`, `#onboarding-steps`, `[data-ob-step]`, `#onboarding-step-title`, `#onboarding-step-content`, `[data-ob]`, `#onboarding-save`, `#onboarding-back`, `#onboarding-later`, progreso/feedback/save-state, `#onboarding-readiness` y `#onboarding-preview`.

Los nombres `data-ob` se traducen a campos exactos del body. No son simples hooks visuales. El orden de `ONBOARDING_STEPS` y su índice están acoplados a navegación y progreso.

### Operaciones

Críticos: filtros/form de incidencias, `#incident-list`, `[data-incident-id]`, `[data-incident-action]`; `#queue-*`, `[data-queue-action]`, job type/id; mantenimiento status/toggle. Los prompts de motivo son parte de la validación visible, aunque deben sustituirse por un diálogo accesible conservando el body requerido.

## Customer

Todos los IDs del HTML aparecen en JS/CSS. Críticos: gates de login/content, botón Google/logout, inputs de perfil y guardado. Importantes: nombre/email/teléfono, feedback, `#upcoming-bookings`, `#booking-history`. No hay `data-*` propio.

## Landing

Todos los IDs del HTML aparecen en JS/CSS. Contratos críticos:

- contenido de negocio: hero/nombre/descripción/CTA/logo, secciones y enlaces;
- `#service-list`, `#service-select`, `#staff-select-field`, `#staff-select`;
- `#booking-form`, inputs de cliente/notas/fotos, submit, estados sin disponibilidad y confirmación;
- `#calendar-picker` se crea/elimina dinámicamente; dentro, días y slots dependen de atributos/closures;
- `#gallery-track`, controles, `#gallery-indicators`, `[data-gallery-index]`;
- auth strip y botón compartido.

`renderCalendarPicker()` inserta un nodo creado por JS en el formulario. Un rediseño no puede asumir que todo el DOM de reserva existe en HTML inicial. Los temas `.template-classic`, `.template-elegant`, `.template-beauty`, `.template-clinic`, `.template-urban` y `.template-minimal` son importantes para el orden/layout, no para la lógica API.

## Clases visuales candidatas a compatibilidad

Las familias `.btn` (Admin) y `.button` (Owner), card/panel, badge/state, feedback/error/success, modal-overlay, tabs/nav y grid son hoy principalmente visuales, pero algunas se usan además en `closest`, `querySelector` o toggles. La futura capa shared debe adoptar selectores múltiples o clases nuevas adicionales (`class="btn ag-button"`) durante la transición.

## Procedimiento seguro antes de tocar DOM

1. Buscar ID/clase/atributo en HTML, JS, CSS, documentación y tests.
2. Buscar formas construidas: prefijos, template strings, `dataset`, `closest` y selectores relativos.
3. Identificar función global o listener delegado y endpoint que activa.
4. Añadir el nuevo markup sin retirar el contrato anterior.
5. Probar teclado, permisos, error y éxito; luego retirar el alias en otro cambio explícito.

