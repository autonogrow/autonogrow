# 02 — Navegación actual

Este documento representa el producto existente; la propuesta se encuentra en `10_proposed_information_architecture.md`.

## Business Admin

Entrada: `autonogrow-admin/index.html?b=<business_slug>#<section>`. El slug es obligatorio para el contexto multinegocio. `showAdminSection(name)` alterna `.admin-tab-active` y `.admin-section-active`, y actualiza el hash. Recargar/restaurar hash mantiene la sección. Los botones de pestaña tienen `data-section`.

```text
Business Admin
├── Resumen (#summary)
│   └── Ver tareas → Crecimiento
├── Crecimiento (#growth)
├── Reservas (#bookings)
│   ├── filtro por profesional
│   ├── Pendientes | Hoy | Mañana | Próximas | Historial
│   ├── confirmar / rechazar / completar / cancelar
│   ├── notas internas / adjuntos / solicitar reseña
│   └── Reagendar → modal (selección completa de nuevo hueco)
├── Conversaciones (#conversations)
│   ├── filtros → lista → detalle
│   ├── responder / sugerencias
│   ├── automatización de conversación
│   └── plantillas y reglas
├── Mensajes automáticos (#messages)
│   ├── activo
│   └── historial
├── Servicios (#services)
├── Equipo (#staff)
│   └── eliminar bloqueado → modal → reserva relacionada
├── Horarios (#schedule)
│   ├── horario semanal
│   └── excepciones
├── Canales (#channels)
│   ├── Instagram Login / reconexión
│   └── WhatsApp Embedded Signup / reconexión
├── Datos del negocio (#business)
└── Reseñas (#reviews)
```

Dependencias ocultas: Resumen y Crecimiento se calculan con estado cargado por otras secciones; Reservas usa servicios/personal; Conversaciones usa plantillas, automatización e integración; Reseñas nace desde una reserva; Canales combina permiso comercial e integración real. El polling/refresco puede volver a renderizar áreas no visibles.

El enlace público abre `../autonogrow-landing/index.html?b=<slug>`. El personal limitado entra por el mismo shell, pero `applyAdminAccess()` oculta secciones no autorizadas y corrige el hash a Reservas.

## Owner

Entrada: `autonogrow-owner/index.html`. `setActiveTab(name)` alterna `.tab.active` y paneles por `data-tab-panel`; no escribe URL/hash ni historial. Una recarga vuelve a la pestaña inicial.

```text
Owner
├── Resumen (métricas; no es pestaña independiente)
├── Negocios
│   └── tarjeta por negocio
│       ├── abrir landing / abrir Admin
│       ├── editar marca y datos
│       ├── gestionar usuarios
│       ├── control de Instagram y WhatsApp
│       │   ├── permiso y aprobación
│       │   ├── capacidades de envío/automatización
│       │   ├── salud/reconexión
│       │   └── candidaturas WhatsApp
│       ├── integración Instagram / candidaturas
│       └── plan, automatización y créditos
├── Nueva empresa
│   ├── inicio de onboarding
│   ├── 15 pasos laterales
│   ├── revisión / vista previa
│   └── activar / guardar para después
├── Incidencias
│   └── filtros → tarjetas → acción
├── Colas y worker
│   └── métricas → jobs → reintentar/cancelar
└── Operaciones
    └── salud técnica → mantenimiento
```

Las tarjetas enlazan a landing/Admin con `?b=<slug>`. “Continuar onboarding” cambia a Nueva empresa mediante JS. Algunas acciones de salud llevan a `Admin#channels`. Los paneles extensos usan `<details>`, por lo que aprobaciones y errores pueden quedar ocultos dentro de un negocio largo.

## Customer

```text
Customer
├── Acceso Google
├── Perfil (edición inline)
├── Próximas reservas
└── Historial
```

No hay router, tabs ni deep links internos. Logout vuelve al gate de acceso.

## Landing

Entrada: `autonogrow-landing/index.html?b=<business_slug>`. Navegación por anclas; el contenido se rellena tras GET del negocio.

```text
Landing pública
├── Cuenta → Customer
├── Inicio
├── Información
├── Servicios
├── Galería (si hay imágenes)
├── Reserva
│   ├── servicio
│   ├── profesional
│   ├── calendario
│   ├── hora
│   ├── datos/fotos
│   └── confirmación
├── Contacto / mapa / redes
└── WhatsApp
```

Las seis plantillas cambian orden y presentación mediante clases CSS, no mediante seis árboles HTML. `data/businesses.json` contiene demos históricas; el flujo de carga actual consulta `/api/businesses/{slug}`.

## Autenticación y URL

- La URL base API se resuelve en `autonogrow-shared/auth.js`; todas las mutaciones reciben CSRF mediante `secureRequestOptions()`.
- Admin y landing usan `?b=`; Owner propaga el slug al construir enlaces; Customer deriva su negocio/reservas de la sesión.
- Admin usa hash como navegación; landing usa hash como ancla; esos significados no deben mezclarse.
- Los OAuth/Embedded Signup abandonan temporalmente la UI o abren el SDK oficial, y retornan a una candidatura pendiente; no son simples cambios de sección.

## Anclas de evidencia en el código actual

- Admin: `autonogrow-admin/admin.js:123` (`showAdminSection`) y `:145-148` (listeners/restauración del hash); botones `data-section` en `autonogrow-admin/index.html`.
- Owner: `autonogrow-owner/owner.js:56` (`setActiveTab`) y `:1042` (listeners sin escritura de URL); pestañas en `autonogrow-owner/index.html:36-41`.
- Customer: `autonogrow-customer/customer.js` carga perfil/reservas tras resolver sesión, sin router interno.
- Landing: `autonogrow-landing/script.js:112-125` carga negocio/servicios/settings/galería y el HTML usa anclas de sección.
- Shared: `autonogrow-shared/auth.js:19-32` aplica CSRF/credenciales al wrapper transversal.
