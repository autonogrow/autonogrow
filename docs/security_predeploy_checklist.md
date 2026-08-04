# Checklist de seguridad predeploy

- [ ] Webhook limitado, firmado y sin procesamiento síncrono.
- [ ] Outbox no almacena tokens; logs/incidencias no contienen payload ni texto.
- [ ] `PROCESS_WEBHOOK_SYNCHRONOUSLY=false` en staging/producción.
- [ ] Unidad worker usa usuario no root y hardening compatible.

## Entorno y transporte

- [ ] `APP_ENV=production`.
- [ ] `COOKIE_SECURE=true`.
- [ ] HTTPS activo y certificado válido.
- [ ] HTTP redirige a HTTPS.
- [ ] El backend no está expuesto directamente; solo el proxy permitido llega a él.
- [ ] `FRONTEND_ORIGINS` contiene únicamente orígenes HTTPS exactos y no contiene `*`.
- [ ] `DATABASE_URL` usa PostgreSQL/psycopg en staging/producción y nunca aparece en logs.
- [ ] `ALLOW_SQLITE_IN_PRODUCTION=false`; cualquier emergencia está aprobada y fechada.
- [ ] Usuario PostgreSQL con mínimo privilegio, red restringida y credenciales fuera del repo.
- [ ] `DATABASE_URL` usa una ruta absoluta fuera del repositorio.
- [ ] `UPLOADS_DIR` usa una ruta absoluta fuera del repositorio y del frontend público.

## Sesión y navegador

- [ ] `SESSION_SECRET` aleatorio, único y de al menos 32 caracteres.
- [ ] `GOOGLE_CLIENT_ID` es el cliente real del entorno.
- [ ] `OWNER_ALLOWED_EMAILS` contiene solo propietarios vigentes.
- [ ] `CSRF_ENABLED=true` y una mutación sin `X-CSRF-Token` devuelve 403.
- [ ] Cookie de sesión confirmada como HttpOnly, Secure, SameSite=Lax y Path=/.
- [ ] Logout elimina cookies de sesión y CSRF.
- [ ] No hay tokens Google en localStorage/sessionStorage.

## Perímetro

- [ ] `RATE_LIMIT_ENABLED=true` y se ha comprobado una respuesta 429.
- [ ] `SECURITY_HEADERS_ENABLED=true`.
- [ ] HSTS aparece por HTTPS en producción.
- [ ] CSP se ha definido y probado en el host que sirve el frontend. No se activa en este sprint porque Google Identity Services y el frontend estático viven fuera de FastAPI; desplegar una política agresiva sin probar podría romper el login.
- [ ] CORS rechaza un origen no permitido.
- [ ] Proxy configurado para preservar la IP de forma fiable antes de usarla para límites/auditoría.

## Autorización y datos

- [ ] Instagram Login usa `state` hasheado, TTL corto, sesión/usuario/negocio y consumo único.
- [ ] `INSTAGRAM_LOGIN_REDIRECT_URI` es HTTPS, exacta y pertenece a `FRONTEND_ORIGINS`.
- [ ] El callback no registra query strings, codes, states, respuestas Meta ni tokens.
- [ ] Una candidatura Instagram no crea integración utilizable antes de aprobación Owner.
- [ ] La aprobación no activa envío ni automatización; un webhook fallido bloquea aprobación.
- [ ] `INSTAGRAM_SIMULATED_ONBOARDING_TEST_ONLY=false` fuera de tests.

- [ ] IDOR probado entre negocios para reservas, servicios, horarios, media y usuarios.
- [ ] Un customer no puede leer citas de otro customer.
- [ ] Una reserva anónima solo gestiona adjuntos con su `booking_manage_token`.
- [ ] Uploads rechazan extensión, MIME, firma o tamaño inválidos.
- [ ] Los adjuntos privados responden solo por el endpoint autorizado; únicamente logos/galería están bajo `/uploads/businesses`.
- [ ] Logs no contienen Google tokens, cookies, teléfonos/emails completos, mensajes ni booking tokens.
- [ ] `audit_logs` recibe login/logout, cambios owner/admin, citas y media.

## Operación

- [ ] Alembic tiene una única head y la base configurada está en ella.
- [ ] Las dependencias de producción/desarrollo se instalan desde locks con `==`.
- [ ] CI completó Ruff, mypy, Bandit, pip-audit, tests, cobertura y migración vacía.
- [ ] `ENABLE_LEGACY_STARTUP_MIGRATIONS=false` y `DATABASE_MIGRATION_CHECK=true`.
- [ ] Backup de base, uploads y keyring cifrada disponible antes de migrar.
- [ ] Backup diario y retenciones 7/4/3 configurados.
- [ ] Backup cifrado y copia fuera del servidor.
- [ ] Restauración probada durante el último mes.
- [ ] Alertas y revisión de 403/429/auditoría definidas.
- [ ] RGPD básico (base legal, información, retención, derechos y encargados) documentado; sigue fuera de este sprint.

## Dry run VPS

- [ ] `python scripts/predeploy_check.py` termina con 0 FAIL.
- [ ] `/etc/autonogrow/backend.env` se creó fuera del repo y no conserva ningún placeholder.
- [ ] `deploy/autonogrow.service.example` se revisó y adaptó a las rutas reales.
- [ ] `deploy/Caddyfile.example` se revisó con el dominio real y no expone la raíz privada de uploads.
- [ ] `/health` devuelve solo `status` y `app`, sin secretos ni rutas internas.
- [ ] El puerto 8000 está cerrado desde Internet y accesible únicamente desde localhost/proxy.
- [ ] HTTPS y redirección desde HTTP están activos.
- [ ] Google OAuth permite el dominio HTTPS real.
- [ ] El backup local fue ejecutado y verificado.
- [ ] El backup externo cifrado está completado o marcado explícitamente como bloqueo preproducción.
- [ ] Se realizó una restauración en una ruta aislada.
# Controles de onboarding

- [ ] Preview protegida por owner y sin reservas/automatización/créditos.
- [ ] Activación solo por endpoint explícito con readiness vigente.
- [ ] Schemas con `extra="forbid"`; URLs peligrosas y slugs reservados rechazados.
- [ ] Plantillas y clonación sin secretos ni datos de otro tenant.
- [ ] Business admin, staff y cliente no acceden a plan, clonación o activación.
# Integraciones Meta Sprint 4D

- Health endpoints protegidos por Owner/business_admin, CSRF y rate limit global.
- `business_id`, proveedor e integración se derivan en servidor; no se aceptan IDs técnicos arbitrarios.
- El claim se confirma antes de descifrar y toda llamada Meta ocurre fuera de transacción larga.
- `health_metadata_json`, respuestas API, métricas, auditoría y logs no contienen tokens, respuestas Meta ni teléfonos completos.
- Predeploy solo inspecciona registro/configuración; nunca ejecuta checkers ni envía mensajes.
- Reconexión mantiene la credencial anterior hasta aprobación Owner y no activa entrega ni automatización.
- `backend/data/autonogrow.db` heredada no se migra ni repara automáticamente.
