# Inventario y revisión de endpoints de seguridad

## WhatsApp Embedded Signup

Los endpoints de inicio, finalización, decisión y reintento son autenticados; todos los POST
usan el middleware CSRF y el inicio/finalización tienen rate limit específico. El state se
guarda como SHA-256 ligado por HMAC a la cookie de sesión y se consume mediante CAS. Las
respuestas y auditorías excluyen authorization code, tokens, App Secret, WABA/phone IDs y el
número completo. La pertenencia Business → WABA → phone y los conflictos entre tenants se
validan server-side antes de crear una candidatura y otra vez al aprobar.

Revisión realizada contra el OpenAPI real del backend (48 paths). `business_admin` y `business_staff` comparten actualmente `require_business_access`; owner puede acceder a cualquier negocio. “CSRF cond.” significa que el endpoint público no exige token sin sesión, pero sí cuando llega la cookie de sesión.

## Autenticación y sistema

| Método | Path | Acceso / rol | CSRF | Scope e IDOR esperado | Estado / observaciones |
|---|---|---|---|---|---|
| GET | `/health` | Público | No | Sin recursos | OK |
| GET | `/api/config/public` | Público | No | Solo configuración pública | OK; no devuelve secretos |
| POST | `/api/auth/google` | Público | Exento | Token validado por Google/audience | OK; excepción CSRF explícita porque crea la sesión |
| GET | `/api/auth/csrf` | Público | No | Emite token firmado; no autentica | OK |
| GET | `/api/auth/me` | Autenticado | No | Usuario de la cookie | OK |
| POST | `/api/auth/logout` | Autenticado | Sí | Usuario de la cookie | OK; elimina sesión y CSRF |

## Owner

| Método | Path | Acceso / rol | CSRF | Scope e IDOR esperado | Estado / observaciones |
|---|---|---|---|---|---|
| GET / POST | `/api/owner/businesses` | Owner | POST: sí | Owner global | OK; creación auditada |
| GET / PATCH | `/api/owner/businesses/{business_slug}` | Owner | PATCH: sí | Negocio por slug | OK; enable/disable/settings auditados |
| GET / POST | `/api/owner/businesses/{business_slug}/users` | Owner | POST: sí | Membership filtrada por `business_id` | OK; asignación auditada |
| PATCH / DELETE | `/api/owner/businesses/{business_slug}/users/{business_user_id}` | Owner | Sí | `BusinessUser.id` + `business_id` | OK; cambio/desactivación auditados |
| GET / POST | `/api/owner/businesses/{business_slug}/media/gallery` | Owner | POST: sí | Media filtrada por `business_id` | OK |
| PATCH / DELETE | `/api/owner/businesses/{business_slug}/media/gallery/{image_id}` | Owner | Sí | `image_id` + `business_id` | OK; borrado auditado |
| POST / DELETE | `/api/owner/businesses/{business_slug}/media/logo` | Owner | Sí | Negocio por slug | OK; upload/borrado auditados |

## Administración de negocio

Todos estos endpoints requieren owner o una membership activa `business_admin`/`business_staff` para el `business_slug` de la URL.

| Método | Path | Acceso / rol | CSRF | Scope e IDOR esperado | Estado / observaciones |
|---|---|---|---|---|---|
| GET / PATCH | `/api/admin/businesses/{business_slug}/settings` | Business access | PATCH: sí | Negocio autorizado por slug | OK; cambios auditados |
| GET / POST | `/api/admin/businesses/{business_slug}/services` | Business access | POST: sí | Servicios por `business_id` | OK |
| PATCH | `/api/admin/businesses/{business_slug}/services/{service_id}` | Business access | Sí | `service_id` + `business_id` | OK |
| GET | `/api/admin/businesses/{business_slug}/bookings` | Business access | No | Reservas por `business_id` | OK |
| GET | `/api/admin/businesses/{business_slug}/panel` | Business access | No | Métricas por `business_id` | OK |
| PATCH | `/api/admin/businesses/{business_slug}/bookings/{booking_id}/status` | Business access | Sí | `booking_id` + `business_id` | OK; confirm/reject/cancel/complete auditados |
| PATCH | `/api/admin/businesses/{business_slug}/bookings/{booking_id}/reschedule` | Business access | Sí | `booking_id` + `business_id` | OK; auditado |
| GET | `/api/admin/businesses/{business_slug}/message-outbox` | Business access | No | Mensajes por `business_id` | OK; filtro `booking_id` se aplica dentro del negocio |
| PATCH | `/api/admin/businesses/{business_slug}/message-outbox/{message_id}/opened` | Business access | Sí | `message_id` + `business_id` | OK |
| PATCH | `/api/admin/businesses/{business_slug}/message-outbox/{message_id}/status` | Business access | Sí | `message_id` + `business_id` | OK |
| GET | `/api/admin/businesses/{business_slug}/review-requests` | Business access | No | Reseñas por `business_id` | OK |
| POST | `/api/admin/businesses/{business_slug}/bookings/{booking_id}/review-request` | Business access | Sí | `booking_id` + `business_id` | OK |
| PATCH | `/api/admin/businesses/{business_slug}/review-requests/{review_request_id}/status` | Business access | Sí | `review_request_id` + `business_id` | OK |
| GET | `/api/admin/businesses/{business_slug}/customers` | Business access | No | Clientes por `business_id` | OK |
| GET / POST | `/api/admin/businesses/{business_slug}/media/gallery` | Business access | POST: sí | Media por `business_id` | OK |
| PATCH / DELETE | `/api/admin/businesses/{business_slug}/media/gallery/{image_id}` | Business access | Sí | `image_id` + `business_id` | OK |
| POST / DELETE | `/api/admin/businesses/{business_slug}/media/logo` | Business access | Sí | Negocio autorizado por slug | OK |
| GET / PATCH | `/api/admin/{business_slug}/availability-settings` | Business access | PATCH: sí | Settings por `business_id` | OK; cambios auditados |
| GET / POST | `/api/admin/{business_slug}/availability-exceptions` | Business access | POST: sí | Excepciones por `business_id` | OK |
| DELETE | `/api/admin/{business_slug}/availability-exceptions/{exception_id}` | Business access | Sí | `exception_id` + `business_id` | OK |

## Customer

| Método | Path | Acceso / rol | CSRF | Scope e IDOR esperado | Estado / observaciones |
|---|---|---|---|---|---|
| GET / PATCH | `/api/customer/profile` | Autenticado | PATCH: sí | Solo el `User` de la sesión | OK |
| GET | `/api/customer/bookings` | Autenticado | No | `customer_user_id` o email Google verificado del usuario | OK; no acepta ids externos |

## Landing, disponibilidad, servicios y reservas

| Método | Path | Acceso / rol | CSRF | Scope e IDOR esperado | Estado / observaciones |
|---|---|---|---|---|---|
| GET / POST | `/api/businesses` | GET público; POST owner | POST: sí | POST owner global | OK; creación auditada |
| GET | `/api/businesses/{slug}` | Público | No | Solo negocio activo | OK |
| GET | `/api/businesses/{business_slug}/services` | Público | No | Servicios activos del negocio activo | OK |
| POST | `/api/businesses/{business_slug}/services` | Business access | Sí | Crea dentro del negocio autorizado | OK |
| GET | `/api/businesses/{business_slug}/availability-settings` | Público | No | Configuración pública del negocio | OK |
| GET | `/api/businesses/{business_slug}/availability` | Público | No | Negocio/servicio de la URL | OK |
| GET | `/api/businesses/{business_slug}/available-slots` | Público | No | Servicio filtrado por `business_id` | OK |
| GET | `/api/businesses/{business_slug}/calendar-days` | Público | No | Reservas agregadas del negocio, sin datos privados | OK |
| POST | `/api/businesses/{business_slug}/booking-requests` | Público; sesión opcional | Cond. | Servicio debe pertenecer al negocio; token de gestión nuevo | OK; alias legacy |
| POST | `/api/businesses/{business_slug}/bookings` | Público; sesión opcional | Cond. | Servicio debe pertenecer al negocio; token de gestión nuevo | OK |
| POST / PATCH | `/api/bookings/{booking_id}/reschedule` | Owner/business asignado | Sí | Dependency resuelve reserva y valida membership de su negocio | OK; query posterior por id queda protegida por la dependency |

## Media y adjuntos

| Método | Path | Acceso / rol | CSRF | Scope e IDOR esperado | Estado / observaciones |
|---|---|---|---|---|---|
| GET | `/api/businesses/{business_slug}/media/gallery` | Público | No | Solo negocio e imágenes activas | OK |
| GET | `/uploads/businesses/*` | Público estático | No | Solo logos/galería/branding | OK; único montaje estático |
| POST | `/api/businesses/{business_slug}/bookings/{booking_id}/attachments` | Owner/business, customer propietario o token anónimo | Cond. | `booking_id` + `business_id`; token comparado constant-time | OK; firma/MIME/tamaño validados |
| GET | `/api/businesses/{business_slug}/bookings/{booking_id}/attachments` | Owner/business asignado | No | `booking_id` + `business_id` | OK; lista privada |
| GET | `/api/businesses/{business_slug}/bookings/{booking_id}/attachments/{attachment_id}/content` | Owner/business, customer propietario o token anónimo | No | `attachment_id` + `booking_id` + `business_id`; path confinado a uploads | Corregido en este sprint |
| GET | `/uploads/{business_slug}/{booking_id}/*` | Ninguno | No | No debe existir montaje | Corregido: ya no se sirve estáticamente |

## Resultado de revisión IDOR

- No se encontró `db.get(Model, id)` en recursos multi-tenant.
- Servicios, reservas, outbox, reseñas, excepciones, memberships, galería y adjuntos combinan el id con `business_id`, o están precedidos por una dependency que valida el negocio de la reserva.
- Customer no recibe un id de customer/reserva arbitrario: las citas se filtran por el usuario de sesión o su email Google verificado.
- Los adjuntos privados dejaron de estar incluidos en el montaje estático. El fichero se resuelve bajo el directorio de uploads y exige permiso sobre la reserva.

## Revisión CSRF

El middleware exige doble token cookie/header en todo `POST`, `PUT`, `PATCH` o `DELETE` que incluya cookie de sesión. Las únicas excepciones son métodos seguros y `/api/auth/google`. Las mutaciones públicas sin sesión —crear reserva y subir con booking token— continúan funcionando; si llevan sesión, el frontend compartido añade CSRF.

## Revisión de auditoría

Confirmados: `login_success`, `logout`, `business_created`, `business_enabled`, `business_disabled`, `user_assigned_to_business`, `user_role_changed`, `user_deactivated`, `booking_confirmed`, `booking_rejected`, `booking_rescheduled`, `booking_cancelled`, `booking_completed`, `media_uploaded`, `media_deleted`, `settings_changed` y `failed_access_403`.

La auditoría guarda ids, acción, email del actor cuando existe y hashes de IP/user-agent. No guarda tokens, cookies, booking tokens, headers completos, teléfonos ni mensajes WhatsApp. Cambios menores de servicios/outbox/reseñas no tienen evento específico; añadirlos requerirá decidir una política de volumen y queda como mejora, no como fallo de autorización.
