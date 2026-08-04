# 03 — Mapa de API consumida por el frontend

## Convenciones y alcance

Se buscaron `fetch`, wrappers y tecnologías persistentes en los cinco frontends. No hay `XMLHttpRequest`, `EventSource` ni `WebSocket`. Admin y Owner declaran un wrapper local de `fetch`; Landing envuelve `window.fetch`; Customer usa `api/jsonRequest`; Shared expone `AutonoGrowAuth.request`. Todos pasan por `secureRequestOptions`, que añade credenciales y CSRF a métodos mutables.

En las tablas: `{slug}` es el negocio de `?b=`, `{business_id}` procede de una tarjeta Owner, e IDs restantes proceden de objetos ya autorizados por backend. “Respuesta/DOM” resume solo campos consumidos; el contrato canónico sigue siendo OpenAPI/Pydantic.

## Admin — negocio, agenda y catálogo

| Método y endpoint | Función/rol | Parámetros/body | Respuesta y DOM | Error/inconsistencia posible |
|---|---|---|---|---|
| GET `/api/admin/businesses/{slug}/panel` | `loadAdminPanel`, personal | slug | negocio + permisos; cabecera y agenda | 401/403 vuelve a acceso; bifurca carga respecto a Admin |
| GET/PATCH `/api/admin/businesses/{slug}/settings` | `loadAdminPanel`, `reloadAdminBusiness`, `saveBusinessSettings`; Admin | PATCH datos, branding, publicación | settings; `#business`, hero/cabecera | feedback inline; el estado alimenta Resumen y Landing |
| GET/PATCH `/api/admin/{slug}/availability-settings` | `load/saveAvailabilitySettings` | semana, zona, reglas de reserva | settings; editor semanal | prefijo legado distinto de otras rutas Admin |
| GET/POST `/api/admin/{slug}/availability-exceptions` | `load/createAvailabilityException` | fecha, tipo, ventanas, motivo | exceptions; lista/editor | carga independiente puede desincronizar Horarios |
| DELETE `/api/admin/{slug}/availability-exceptions/{id}` | `deleteAvailabilityException` | id | 204; lista recargada | usa `alert` en error |
| GET/POST `/api/admin/businesses/{slug}/services` | `load/createAdminService` | nombre, descripción, precio, duración, activo | `services`; catálogo y selects | servicios son dependencia de personal/reserva |
| PATCH `/api/admin/businesses/{slug}/services/{id}` | `saveAdminService` | campos editables | service; lista recargada | render completo puede perder foco |
| GET/POST `/api/admin/businesses/{slug}/staff` | `loadStaffMembers`, `createStaffMember` | perfil/rol/capacidad | `staff`; equipo y filtros | también condiciona disponibilidad y reservas |
| PATCH/DELETE `/api/admin/businesses/{slug}/staff/{id}` | `save/toggle/deleteStaffMember` | perfil/activo o borrado | miembro o bloqueo con citas | DELETE puede abrir `#staff-removal-modal` |
| GET/PUT `/api/admin/businesses/{slug}/staff/{id}/availability` | `load/saveStaffAvailability` | semana individual | disponibilidad; editor del miembro | carga bajo demanda y render anidado |
| PUT `/api/admin/businesses/{slug}/staff/{id}/services` | guardado de miembro | `service_ids` | asignación; tarjeta | se ejecuta tras PATCH: éxito parcial posible |
| GET `/api/admin/businesses/{slug}/my-staff-availability` | `loadMyStaffAvailability`, personal | — | agenda propia | fallo no debe habilitar otras áreas |
| GET `/api/admin/businesses/{slug}/bookings` | `loadBookings` | — | `bookings`; métricas/listas | enriquece después con adjuntos/reseñas; estado parcial |
| PATCH `/api/admin/businesses/{slug}/bookings/{id}/status` | `updateBookingStatus` | `status` | booking; refresco | puede generar outbox; feedback por tarjeta |
| PATCH `/api/admin/businesses/{slug}/bookings/{id}/internal-notes` | `saveInternalNotes` | notes | notas | polling captura/restaura borradores, pero añade complejidad |
| GET `/api/businesses/{slug}/bookings/{id}/attachments` | `enrichBookingsWithAttachments` | id | attachments; tarjeta | ruta pública protegida por contexto/token; N llamadas por reservas |
| GET `/api/businesses/{slug}/available-slots` | modal `loadRescheduleSlots` | service, staff, date | slots; modal | ruta pública usada dentro de Admin |
| PATCH `/api/bookings/{id}/reschedule` | `confirmReschedule` | nuevo inicio/profesional y token/contexto | booking | endpoint sin slug en path; conflicto de hueco recarga opciones |
| GET `/api/admin/businesses/{slug}/review-requests` | `loadReviewRequests` | — | requests; Reservas/Reseñas/Resumen | si falla se vacía el mapa local |
| POST `/api/admin/businesses/{slug}/bookings/{id}/review-request` | `createReviewRequest` | canal/plantilla | request | depende de cita completada |
| PATCH `/api/admin/businesses/{slug}/review-requests/{id}` | cambio de reseña | status | request | estado optimista no centralizado |

## Admin — conversaciones, mensajes, canales y medios

| Método y endpoint | Función | Body/respuesta/DOM | Observación |
|---|---|---|---|
| GET/POST `/api/admin/businesses/{slug}/conversations` | `loadConversations`, `createConversation` | filtros o conversación de prueba; lista | POST está reservado a Admin; lista y detalle comparten estado global |
| GET `/api/admin/businesses/{slug}/conversations/{id}` | `selectConversation` | conversación/mensajes; thread | en paralelo con sugerencias; una puede fallar |
| GET `/api/admin/businesses/{slug}/conversations/{id}/suggestions` | `selectConversation` | sugerencias | mismo riesgo parcial |
| POST `/api/admin/businesses/{slug}/conversations/{id}/messages` | `sendConversationMessage` | texto, canal/modo | mensaje/outbox; thread | resultado integrado/asistido se explica de modo distinto |
| POST `/api/admin/businesses/{slug}/conversations/{id}/assisted-delivery` | acción asistida | contenido/canal | instrucción/estado | requiere acción humana fuera de plataforma |
| GET `/api/admin/businesses/{slug}/conversations/{id}/automation` | carga de detalle | estado por conversación | panel de automatización | se combina con estado global |
| PATCH `/api/admin/businesses/{slug}/conversations/{id}/automation` | pausa/reactivación | estado/minutos | detalle | refresca lista, hilo y operaciones |
| POST `/api/admin/businesses/{slug}/conversations/{id}/suggestions/{sid}/send` | enviar sugerencia | ajustes/texto | mensaje + sugerencia | doble entidad cambia en una acción |
| PATCH `/api/admin/businesses/{slug}/conversations/{id}/suggestions/{sid}` | descartar/editar | status/text | sugerencia | feedback inline común |
| PATCH `/api/admin/businesses/{slug}/conversations/{id}/status` | `changeConversationStatus` | status | conversación | refresco múltiple |
| GET/POST `/api/admin/businesses/{slug}/conversation-templates` | `load/createConversationTemplate` | plantilla | `#conversation-template-list` | `innerHTML` y handlers globales |
| PATCH/DELETE `/api/admin/businesses/{slug}/conversation-templates/{id}` | `save/deleteConversationTemplate` | campos/— | lista y automation | recarga tres superficies |
| GET `/api/admin/businesses/{slug}/conversation-automation` | `loadConversationAutomation` | settings, usage, rules, templates | panel | en paralelo con integrations/status |
| PATCH `/api/admin/businesses/{slug}/conversation-automation/settings` | `saveConversationAutomationSettings` | enabled, threshold, limit, pause | panel | valida confirmación al recargar |
| PATCH `/api/admin/businesses/{slug}/conversation-automation/rules/{intent}` | `saveConversationAutomationRule` | mode, template, active | regla | compara respuesta y recarga para detectar divergencia |
| GET `/api/admin/businesses/{slug}/integrations/status` | `loadConversationAutomation` | estado resumido | banner de integración | fallo se tolera como `null`, puede parecer desconectado |
| GET `/api/admin/businesses/{slug}/message-outbox` | `loadMessageOutbox` | mensajes | métricas, activo e historial | polling por fingerprint |
| PATCH `/api/admin/businesses/{slug}/message-outbox/{id}/opened` | marcar abierto | opened | tarjeta | refresca outbox |
| PATCH `/api/admin/businesses/{slug}/message-outbox/{id}/status` | cambiar estado | status | tarjeta | acción manual convive con worker |
| GET `/api/admin/businesses/{slug}/channel-onboarding` | `loadBusinessChannelOnboarding` | canales/capacidades | `#channel-onboarding-list` | en paralelo con health |
| POST `/api/admin/businesses/{slug}/channel-onboarding/{channel}/request` | `requestBusinessChannelConnection` | confirmación autoridad | solicitud | fallback para canales no Meta actuales |
| GET `/api/admin/businesses/{slug}/channels/health` | misma carga | estados seguros | tarjetas canal | si falla, onboarding sigue sin health |
| POST `/api/admin/businesses/{slug}/channels/{channel}/health-check` | `handleChannelHealthAction` | `{}` | tarea creada/existente | respuesta es encolada, no resultado final |
| POST `/api/admin/businesses/{slug}/channels/instagram/reconnect` | reconectar | `{}` | URL OAuth | navega fuera tras validar host/prefijo |
| POST `/api/admin/businesses/{slug}/integrations/instagram/oauth/start` | conexión Instagram | purpose | URL OAuth | redirección; retorno/candidatura no vive en mismo DOM |
| POST `/api/admin/businesses/{slug}/integrations/whatsapp/embedded-signup/start` | `launchWhatsAppEmbeddedSignup` | purpose | config pública/state | depende del SDK Meta y evento `postMessage` validado |
| POST `/api/admin/businesses/{slug}/integrations/whatsapp/embedded-signup/complete` | `completeWhatsAppEmbeddedSignup` | state, code, evento e IDs Meta | candidate/status | timeout/cancel/code incompleto tienen mensajes distintos |
| POST/DELETE `/api/admin/businesses/{slug}/media/logo` | `upload/deleteAdminMedia` | multipart/— | negocio recargado | sesión conserva subida en curso |
| GET/POST `/api/admin/businesses/{slug}/media/gallery` | `load/uploadAdminGallery` | multipart + alt | images | error de media especializado |
| PATCH/DELETE `/api/admin/businesses/{slug}/media/gallery/{id}` | `handleAdminGalleryAction` | active, alt, position/— | galería | selectores dinámicos por ID |

## Owner

| Método y endpoint | Función/superficie | Body y respuesta consumida | Riesgo de estado/UX |
|---|---|---|---|
| GET/POST `/api/owner/businesses` | `loadBusinesses`, alta legado | creación; negocios + métricas/health | lista central; cada negocio dispara cargas adicionales |
| PATCH `/api/owner/businesses/{slug}` | editor/estado | settings o status+reason | editar y suspender comparten tarjeta |
| GET/POST `/api/owner/businesses/{slug}/users` | usuarios | email, role; users | subpanel por negocio |
| PATCH/DELETE `/api/owner/businesses/{slug}/users/{id}` | usuarios | role/— | confirmaciones nativas |
| POST/DELETE `/api/owner/businesses/{slug}/media/logo` | media | multipart/— | mismo patrón que Admin, implementación duplicada |
| GET/POST `/api/owner/businesses/{slug}/media/gallery` | media | images/multipart | carga por tarjeta |
| PATCH/DELETE `/api/owner/businesses/{slug}/media/gallery/{id}` | media | active, alt, position/— | tarjeta vuelve a cargar |
| GET `/api/owner/system/health` | `loadOperationsStatus` | salud/mantenimiento/detalle | imprime detalle técnico incluido JSON |
| POST `/api/owner/system/maintenance/{enable|disable}` | `toggleMaintenance` | reason en query | prompt nativo, acción global peligrosa |
| GET `/api/owner/system/queue-status` | `loadQueueStatus` | métricas/jobs | terminología interna |
| POST `/api/owner/queue/{job_type}/{job_id}/{retry|cancel}` | `updateQueueJob` | reason | prompt; IDs técnicos delante de impacto |
| GET `/api/owner/incidents` | `loadIncidents` | filtros de estado/tipo/negocio; incidents/open_count | resumen depende de esta carga |
| PATCH `/api/owner/incidents/{id}` | `updateIncident` | action | controles por tarjeta |
| GET `/api/owner/businesses/{id}/channel-controls` | `loadOwnerChannelControls` | controles/capacidades | se combina con candidates y health |
| PUT `/api/owner/businesses/{id}/channel-controls/{channel}/access` | acción channel | permiso + reason | permiso comercial separado de integración |
| POST `/api/owner/businesses/{id}/channel-controls/{channel}/{request|approve|suspend|revoke}` | acción channel | autoridad/reason | una función construye varias rutas dinámicas |
| PATCH `/api/owner/businesses/{id}/channel-controls/{channel}/capabilities` | acción channel | delivery/automation flags, reason | preservar independencia de aprobación |
| GET `/api/owner/businesses/{id}/channels/health` | control canal | health channels | carga paralela tolera error |
| POST `/api/owner/businesses/{id}/channels/{channel}/{health-check|retry-subscription|request-reconnection}` | acción health | reason cuando aplica | resultado asíncrono y panel se recarga |
| GET `/api/owner/businesses/{id}/integrations/whatsapp/embedded-signup/candidates` | control canal | candidates | cola queda escondida en tarjeta |
| POST `/api/owner/businesses/{id}/integrations/whatsapp/embedded-signup/candidates/{attempt}/{retry|approve|reject}` | acción candidate | reason | rutas construidas según botón |
| GET `/api/owner/businesses/{id}/integrations/instagram` | `loadOwnerIntegration` | integración | paralelo con OAuth candidates |
| POST `/api/owner/businesses/{id}/integrations/instagram` | vía avanzada | account_id, access_token, expiry, reason | token se borra del input/payload local; UI técnica |
| POST `/api/owner/businesses/{id}/integrations/instagram/reconnect` | vía avanzada | mismas credenciales | compatibilidad administrativa |
| POST `/api/owner/businesses/{id}/integrations/instagram/verify` | integración | — | verificación inmediata |
| POST `/api/owner/businesses/{id}/integrations/instagram/disconnect` | integración | reason | acción peligrosa con confirm/prompt |
| DELETE `/api/owner/businesses/{id}/integrations/instagram/credentials` | integración | reason | irreversible desde UI |
| GET `/api/owner/businesses/{id}/integrations/instagram/oauth/candidates` | `loadOwnerIntegration` | attempts | cola anidada |
| POST `/api/owner/businesses/{id}/integrations/instagram/oauth/start` | OAuth Owner | purpose | URL autorización |
| POST `/api/owner/businesses/{id}/integrations/instagram/oauth/candidates/{attempt}/{approve|reject}` | decisión | reason | aprobación separada |
| POST `/api/owner/businesses/{id}/integrations/instagram/oauth/candidates/{attempt}/webhook/retry` | reparación | — | detalle técnico visible |
| GET/PATCH `/api/owner/businesses/{id}/automation-settings` | `load/mutateOwnerAutomation` | flags/plan | subpanel comercial |
| GET `/api/owner/businesses/{id}/automation-credits/transactions?limit=100` | historial | transactions | lista larga sin paginación UI |
| POST `/api/owner/businesses/{id}/automation-credits/{adjustments|purchase}` | acciones | cantidad/reason | prompt y confirm nativos |
| POST `/api/owner/businesses/{id}/automation-credits/{period|usage}/*` | periodos/uso | fechas/cantidad/reason | varias acciones dinámicas, lenguaje técnico |

## Owner — onboarding guiado

| Método y endpoint | Paso/body | DOM/observación |
|---|---|---|
| GET `/api/owner/onboarding/templates` | — | selector de plantilla |
| POST `/api/owner/businesses/onboarding` | name, slug, template_key | crea sesión y abre workspace |
| GET `/api/owner/businesses/{id}/onboarding` | — | negocio, sesión y estados de 15 pasos |
| PUT `/api/owner/businesses/{id}/onboarding/identity` | identidad/idioma/zona/moneda | paso Identidad |
| PUT `.../onboarding/contact` | contacto, ubicación y enlaces | Contacto |
| PUT `.../onboarding/services` | array de servicios | Servicios |
| PUT `.../onboarding/staff` | array de perfiles | Personal |
| PUT `.../onboarding/schedules` | zona + semana | Horarios |
| PUT `.../onboarding/booking` | reglas y capacidad | Reservas |
| PUT `.../onboarding/branding` | colores | Branding |
| PUT `.../onboarding/landing` | headline, descripción, CTA, SEO | Landing |
| PUT `.../onboarding/automations` | enabled + mensajes | Automatizaciones |
| POST `.../onboarding/steps/integrations/skip` | reason | integración opcional marcada revisada |
| PUT `.../onboarding/credits` | plan/saldos/periodo | Plan y créditos |
| GET `/api/owner/businesses/{id}/readiness` | — | bloqueantes/avisos/version; `#onboarding-readiness` |
| GET `/api/owner/businesses/{id}/preview` | — | preview textual privado |
| POST `/api/owner/businesses/{id}/activate` | reason, expected_readiness_version | protección contra readiness obsoleto |

Los endpoints de suspender/reactivar también son invocados desde la tarjeta de negocio. Su separación debe conservar motivos, auditoría y comprobaciones de readiness.

## Customer

| Método/endpoint | Función | Body/respuesta/DOM | Errores |
|---|---|---|---|
| GET `/api/customer/profile` | `loadCustomer` | user; perfil/cabecera | 401 agenda regreso al login |
| PATCH `/api/customer/profile` | submit perfil | name, phone | user + feedback | conserva datos en formulario |
| GET `/api/customer/bookings` | `loadCustomer` | próximas/historial | listas | mensaje común si backend falla |

## Landing

| Método/endpoint | Función | Parámetros/body | Respuesta/DOM y error |
|---|---|---|---|
| GET `/api/businesses/{slug}` | `loadBusiness` | slug | negocio; toda la página; not-found o backend-error |
| GET `/api/businesses/{slug}/services` | `loadBusiness` | — | array; catálogo/select; fallo se tolera vacío |
| GET `/api/businesses/{slug}/availability-settings` | `loadBusiness` | — | horizonte; fallback 14 días |
| GET `/api/businesses/{slug}/media/gallery` | `loadBusiness` | — | images; carrusel; fallback vacío |
| GET `/api/businesses/{slug}/services/{service_id}/staff` | `loadStaffForService` | service | staff; select/fallback contacto | versionado local evita carrera al cambiar servicio |
| GET `/api/businesses/{slug}/available-slots` | `fetchAvailableSlots` | date/service/staff | slots; botones | conflicto/carga y error visible en reserva |
| GET `/api/businesses/{slug}/calendar-days` | `fetchCalendarDays` | from/to/service/staff | disponibilidad por día | se recalcula al cambiar selección |
| POST `/api/businesses/{slug}/bookings` | submit | cliente, service, staff, start, notes, source | booking + manage token; confirmación | 409 recarga huecos; usa `alert` |
| POST `/api/businesses/{slug}/bookings/{id}/attachments` | `uploadBookingPhotos` | multipart + `X-Booking-Token` | attachments | cita ya existe aunque fotos fallen; se explica explícitamente |

## Compartido

| Método/endpoint | Consumidor | Uso |
|---|---|---|
| GET `/api/config/public` | configuración inicial | origen/config pública segura |
| GET `/api/auth/csrf` | `getCsrfToken` | token solo en header; cache en memoria |
| GET `/api/auth/google` | flujo Google | inicio/redirect de autenticación |
| GET `/api/auth/me` | `getMe` | sesión/rol; gates de las cuatro apps |
| POST `/api/auth/logout` | `logout` | cierra sesión y limpia estado local |

## Duplicación y riesgos arquitectónicos

1. Settings/media se implementan por separado en Admin y Owner; cambian rutas, selectores y manejo de errores.
2. Admin mezcla rutas `/api/admin/{slug}`, `/api/admin/businesses/{slug}` y rutas públicas de slots/reschedule. Es válido hoy, pero aumenta el riesgo de construir mal el contexto.
3. Owner realiza al menos tres llamadas paralelas por panel de canal y dos por integración, además de usuarios/media/automatización. Con muchos negocios aparece un patrón N×dominios sin carga progresiva global.
4. Varias acciones realizan una mutación y luego múltiples GET. Si uno falla, la operación puede haber sido correcta aunque el feedback sugiera incertidumbre.
5. `integrations/status` fallido se degrada a “desconectado” en vez de “estado desconocido”. Conviene diferenciarlo en el rediseño.
6. API, render y feedback viven en las mismas funciones. Un cliente compartido futuro debe normalizar JSON, abortos, errores seguros y estados, pero nunca retirar el control de autorización del servidor.

