# 01 — Inventario frontend

## Dimensión del código inspeccionado

| Aplicación | HTML | JavaScript | CSS | Rol principal |
|---|---:|---:|---:|---|
| Admin | 580 líneas | 3.906 | 1.530 | Business Admin y personal limitado |
| Owner | 194 | 1.138 | 162 | Operador global de AutonoGrow |
| Customer | 40 | 68 | 20 | Cliente autenticado |
| Landing | 199 | 1.005 | 838 | Visitante/cliente público |
| Shared | — | 95 | 217 | Autenticación y páginas legales |

Los recuentos corresponden a los archivos principales actuales, no a complejidad efectiva.

## Business Admin

La raíz es `autonogrow-admin/index.html`; `admin.js` oculta/muestra `.admin-section` mediante `showAdminSection()` y carga casi todos los dominios tras resolver `?b=<slug>`.

| Vista/panel | Selector principal | Finalidad y rol | Acceso/acciones | Datos y API | Estados/responsive/dependencias |
|---|---|---|---|---|---|
| Acceso | `#admin-login` | Autenticar Admin/personal | Google | `/api/auth/*`, settings/panel | Login, acceso denegado y backend no disponible; `AutonoGrowAuth` |
| Cabecera | `.admin-header` | Contexto de negocio y sincronización | abrir landing, refrescar, salir | settings/panel | punto y texto de sincronización; se apila en móvil |
| Resumen | `#summary` | Pulso global | ir a Crecimiento | settings, servicios, equipo, agenda, reservas, mensajes y reseñas ya cargados | 12 tarjetas; vacío implícito en cero; grid colapsa |
| Crecimiento | `#growth` | Lista diaria priorizada | navegar a dominio de cada tarea | deriva del estado global | progreso, tareas hechas/pendientes; `renderGrowth()` |
| Reservas | `#bookings` | Gestionar citas | filtrar profesional; Pendientes/Hoy/Mañana/Próximas/Historial; confirmar, completar, cancelar, notas, adjuntos, reagendar, reseña | bookings, status, notes, attachments, slots, reschedule, review requests | carga/error/lista vacía; tarjetas, no agenda visual |
| Reagendar | `#reschedule-modal` | Proceso completo de cambio | elegir servicio, profesional, día y hora, confirmar/cerrar | servicios, slots, reschedule | carga de huecos/error; overlay con scroll; semántica incompleta |
| Conversaciones | `#conversations` | Inbox multicanal | filtrar, seleccionar, responder, sugerencias, pausar/activar automatización, plantillas, conversación de prueba | conversations, messages, suggestions, templates, automation, integration status | lista/detalle/errores parciales; dos columnas, una <=820 px |
| Mensajes automáticos | `#messages` | Seguimiento de outbox | filtrar, marcar abierto/estado, ver activo/historial | message-outbox | métricas, vacío/error; tarjetas |
| Servicios | `#services` | Catálogo | crear/editar/activar | services | formularios generados; feedback inline; una columna móvil |
| Equipo | `#staff` | Personal y asignaciones | crear/editar/desactivar/eliminar; servicios y disponibilidad individual | staff, staff services/availability | inactivos y bloqueo de borrado; mucho DOM dinámico |
| Bloqueo al eliminar | `#staff-removal-modal` | Explicar citas que impiden eliminación | cerrar/ir a cita | respuesta DELETE staff | `role=dialog`; sin gestión completa de foco |
| Horarios | `#schedule` | Disponibilidad base y excepciones | guardar semana, añadir ventanas/excepciones, borrar | availability settings/exceptions | cargas independientes; 5 columnas hasta 820 px |
| Canales | `#channels` | Incorporación y salud Meta | solicitar/conectar/reconectar/comprobar | onboarding, health, Instagram OAuth, WhatsApp Embedded Signup | estados por canal y feedback; SDK Meta bajo demanda |
| Datos del negocio | `#business` | Datos, marca, tema y galería | editar, publicar/suspender, subir/eliminar/reordenar medios | settings/media | feedback y subida persistida en `sessionStorage`; grid móvil |
| Reseñas | `#reviews` | Solicitudes postservicio | crear, copiar/abrir WhatsApp, cambiar estado | review requests | pendiente/historial, vacío/error |

El rol de personal recibe `/panel` y queda restringido a Agenda/Conversaciones según permisos; ocultar UI no reemplaza los controles del backend.

## Owner

`autonogrow-owner/index.html` contiene cinco pestañas actuales. Cada tarjeta de negocio amplía una gran superficie operativa y dispara cargas adicionales.

| Vista/panel | Selector principal | Finalidad | Acciones/datos | Estados y dependencias |
|---|---|---|---|---|
| Acceso/cabecera | `#owner-login`, `.owner-header` | Autenticación Owner | auth, refrescar, salir | acceso denegado/backend no disponible |
| Resumen | `#summary-grid` | 6 métricas globales | negocios, activos, reservas/mensajes/reseñas pendientes, incidencias | deriva de negocios e incidencias |
| Negocios | `#businesses-panel`, `#business-list` | Lista y operación por negocio | abrir landing/Admin, continuar onboarding, suspender/reactivar | `/api/owner/businesses` |
| Editor de negocio | `[data-owner-editor]` | Marca y datos | editar, logo/galería | settings/media; feedback local |
| Usuarios | `[data-owner-users-id]` | Acceso al negocio | añadir/cambiar rol/eliminar | users CRUD |
| Control de canales | `[data-owner-channel-control-id]` | Permiso, aprobación, capacidades y salud | conceder/solicitar/aprobar/suspender/revocar; envío/automatización; checks/reconexión | channel-controls, candidates, health |
| Instagram | `[data-owner-integration-id]` | Candidaturas/integración | OAuth, aprobar/rechazar, reintentar webhook, verificar, desconectar, borrar credenciales; formulario legado avanzado | integration/OAuth endpoints |
| Plan y automatización | `[data-owner-automation-id]` | Plan, capacidad y créditos | ajustar, comprar, periodos/uso, historial | automation settings/credits |
| Nueva empresa | `#new-business-panel` | Alta guiada | iniciar, continuar 15 pasos, omitir, previsualizar, activar | onboarding endpoints/templates |
| Formulario legado | `#business-form` | Alta directa compatible | crear negocio | oculto; `/api/owner/businesses` POST |
| Incidencias | `#incidents-panel` | Casos del sistema | filtrar y resolver/silenciar/reabrir | incidents GET/PATCH |
| Colas y worker | `#queues-panel` | Estado de inbox/outbox | reintentar/cancelar job con motivo | queue-status y queue actions |
| Operaciones | `#operations-panel` | Salud/maintenance | activar/desactivar mantenimiento | system health/maintenance; JSON técnico en `pre` |

## Customer

| Vista | Selector | Uso | API/estados |
|---|---|---|---|
| Acceso | `#customer-login` | Google | auth compartida; 401 vuelve al login |
| Perfil | `#customer-profile` | Ver/editar nombre y teléfono | GET/PATCH `/api/customer/profile`; feedback textual |
| Próximas | `#upcoming-bookings` | Reservas activas | GET `/api/customer/bookings`; tarjetas/vacío/error |
| Historial | `#booking-history` | Reservas pasadas | misma respuesta segmentada |

## Landing pública

| Bloque | Selector | Función/acciones | Datos y estados |
|---|---|---|---|
| Franja de cuenta | `#auth-strip` | entrar/abrir “Mis citas” | auth compartida; se oculta/muestra |
| Hero | `#inicio`, `#hero-*` | propuesta y CTA reserva | negocio/tema; imagen o gradiente |
| Navegación rápida | `.quick-nav` | anclas a información, servicios, galería, reserva y contacto | hash/scroll |
| Información/promoción | `#informacion` | descripción y mensajes | negocio; promociones actualmente vacías |
| Servicios | `#servicios` | catálogo y selección | GET services; conduce al select de reserva |
| Galería | `#galeria` | carrusel | GET media/gallery; controles e indicadores |
| Reserva | `#reserva`, `#booking-form` | servicio → profesional → día → hora → datos → fotos → confirmar | staff, calendar-days, slots, bookings, attachments | carga, sin profesionales, conflicto de hueco, confirmación |
| Contacto | `#contacto` | dirección, teléfono, mapa, Instagram | datos de negocio/enlaces externos |
| CTA final | `#final-whatsapp-cta` | contacto WhatsApp | URL calculada |
| Footer | `footer` | marca/legal | enlaces estáticos |

No existe una sección independiente de equipo ni una sección de reseñas/testimonios; el profesional aparece solo dentro de la reserva y las reseñas son un enlace externo si existe.

## Compartido

- `autonogrow-shared/auth.js`: base URL, CSRF, `request`, sesión, Google Identity, logout y render del botón.
- `auth.css`: franja/botón de autenticación.
- `legal.css`: estilos de privacidad y eliminación de datos.
- Contrato transversal: `window.AutonoGrowAuth` debe cargarse antes de scripts consumidores.

## Estados transversales observados

La carga se representa con texto, contenido vacío o botones desactivados según pantalla; no existe loader compartido. Los errores alternan entre `alert`, `confirm`/`prompt`, feedback inline, reemplazo de `innerHTML` y consola. Los vacíos son normalmente tarjetas con texto, pero no hay anatomía ni acción consistente. Esta inconsistencia es una oportunidad prioritaria de sistema visual, no un motivo para cambiar contratos en 5A.1.

