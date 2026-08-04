# Salud de integraciones Meta

Consulta de contratos oficiales: 2026-08-04. Instagram y WhatsApp usan la versión validada en configuración (`META_GRAPH_API_VERSION` y las versiones específicas existentes; por defecto `v23.0`). El health worker nunca elige una versión enviada por frontend.

Fuentes oficiales de Meta:

- Instagram profesional, permisos y mensajería: <https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api>
- Instagram `GET/POST /{ig_user_id}/subscribed_apps`: <https://www.postman.com/meta/instagram/request/23987686-27309084-5d59-42b6-9b81-379cf9b1e61d>
- WhatsApp `debug_token`: <https://www.postman.com/meta/whatsapp-business-platform/request/i1mz7w8/debug-token>
- WABA `phone_numbers`: <https://www.postman.com/meta/whatsapp-business-platform/request/e9ady51/get-phone-numbers>
- WABA `subscribed_apps`: <https://www.postman.com/meta/whatsapp-business-platform/request/tl2wk2j/get-all-subscriptions-for-a-waba>

## Modelo

`integration_status` sigue expresando el estado persistido general. `health_status` expresa solamente la última comprobación: `unknown`, `healthy`, `warning`, `degraded`, `action_required`, `revoked`, `suspended` o `error`. El control comercial (`BusinessChannelControl`), aprobación Owner, entrega y automatización permanecen independientes.

La integración almacena fechas de última/próxima comprobación, fallos consecutivos y un error seguro. `health_metadata_json` está limitado a `token_expiry_status`, `subscription_status`, `asset_status`, flags `blocking`/`reconnection_required` y hechos acotados como tipo profesional o estado compuesto del teléfono. No contiene tokens, respuestas Meta, scopes crudos, teléfonos completos ni nuevos identificadores.

La ausencia de expiración se clasifica `unknown`; no implica token permanente. Umbrales predeterminados: warning 14 días y critical 3 días.

## Jobs y worker

`meta_integration_jobs` registra `health_check`, `retry_subscription` y `attempt_cleanup`. La clave de idempotencia es única y además se comprueba que no exista otro trabajo activo para la misma integración/tipo. PostgreSQL reclama mediante `FOR UPDATE SKIP LOCKED`; SQLite solo admite el modo single-worker configurado.

El ciclo es:

1. scheduler acotado crea trabajos vencidos;
2. el worker reclama y confirma el claim;
3. valida `business_id`, canal, proveedor y conflictos tenant;
4. descifra después de esas validaciones;
5. llama a hosts Meta fijos sin transacción abierta;
6. persiste resultado en otra transacción;
7. recupera locks caducados y aplica backoff con jitter.

Inbox y outbox se procesan antes del lote de mantenimiento. El heartbeat usa `current_job_type=meta_integration`. Deshabilitar `META_INTEGRATION_HEALTH_CHECK_ENABLED` impide programar health checks, pero no impide arrancar el worker ni limpiar credenciales candidatas caducadas.

## Diagnóstico y transiciones

Instagram comprueba credencial, expiración, scopes concedidos al conectar, perfil, account ID, tipo Business/Creator y suscripción `messages`. WhatsApp inspecciona token/app/scopes/WABA, pertenencia del teléfono, registro, estado seguro disponible y suscripción de app.

- Primer fallo transitorio: `warning`, retry y contador +1.
- Umbral: `degraded`; un timeout nunca revoca.
- Suscripción ausente: `degraded`; se agenda reparación idempotente.
- Token revocado: health e integración `revoked`, entrega efectiva bloqueada.
- Número suspendido: health `suspended`, integración `error`.
- Reparación completa: `healthy`, contador cero; una integración degradada puede volver a `connected`.

Un envío correcto solo actualiza `last_success_at`; no establece health healthy. Ninguna comprobación cambia plan, control comercial, entrega habilitada ni automatización habilitada.

## Autorrecuperación y reconexión

Solo se reintentan lecturas y `subscribed_apps` cuando el token y permisos siguen siendo utilizables. Nunca se inicia OAuth/Embedded Signup en background, se registra un PIN, se sustituye cuenta/número ni se activan capacidades.

La reconexión reutiliza los attempts de Sprints 4B/4C con propósito `reconnect`, state nuevo y candidatura Owner. La credencial vigente permanece hasta la aprobación; al aprobar, entrega y automatización siguen sin activarse automáticamente.

## Configuración

Variables: `META_INTEGRATION_HEALTH_CHECK_ENABLED`, `META_INTEGRATION_HEALTH_CHECK_INTERVAL_HOURS`, `META_TOKEN_EXPIRY_WARNING_DAYS`, `META_TOKEN_EXPIRY_CRITICAL_DAYS`, `META_INTEGRATION_FAILURE_THRESHOLD`, `META_INTEGRATION_CLEANUP_INTERVAL_HOURS`, `META_EXPIRED_ATTEMPT_RETENTION_DAYS`, `META_INTEGRATION_HEALTH_BATCH_SIZE`, `META_INTEGRATION_HEALTH_JOB_TIMEOUT_SECONDS` y `META_INTEGRATION_HEALTH_LOCK_TTL_SECONDS`.

La base heredada `backend/data/autonogrow.db` no tiene revisión Alembic completa. No debe recibir stamp, upgrade ni reparación automática: requiere inventario y decisión manual independiente antes de cualquier migración.
