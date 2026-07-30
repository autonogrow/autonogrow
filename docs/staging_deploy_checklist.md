# Checklist de despliegue staging

- [ ] Ejecutar `alembic upgrade head` y confirmar head `20260730_03`.
- [ ] Confirmar `PROCESS_WEBHOOK_SYNCHRONOUSLY=false`.
- [ ] Instalar backend y worker como servicios separados; un solo worker activo.
- [ ] Verificar heartbeat y colas desde owner sin exponer payloads.

Registrar fecha, responsable, dominio, versión desplegada y resultado de cada punto. No marcar producción como lista basándose únicamente en este staging.

## Dominio, red y proxy

- [ ] Dominio o subdominio elegido: `staging.example.com` sustituido por el real.
- [ ] DNS A/AAAA apunta exclusivamente al VPS de staging esperado.
- [ ] Puertos 80 y 443 abiertos.
- [ ] Puerto 8000 cerrado desde Internet y accesible solo desde localhost/proxy.
- [ ] Caddy o Nginx activo y configuración validada.
- [ ] HTTP redirige a HTTPS.
- [ ] Certificado HTTPS válido, cadena completa y renovación configurada.
- [ ] `GET /health` por HTTPS devuelve 200 y el JSON mínimo esperado.

## Entorno y autenticación

- [ ] `APP_ENV=production`.
- [ ] `DATABASE_MIGRATION_CHECK=true` y `ENABLE_LEGACY_STARTUP_MIGRATIONS=false`.
- [ ] Política SQLite validada: timeout 5000, WAL y synchronous NORMAL.
- [ ] `COOKIE_SECURE=true`.
- [ ] `CSRF_ENABLED=true`, `RATE_LIMIT_ENABLED=true` y `SECURITY_HEADERS_ENABLED=true`.
- [ ] `FRONTEND_ORIGINS` contiene únicamente el dominio HTTPS real de staging.
- [ ] `DATABASE_URL` y `UPLOADS_DIR` apuntan a `/var/lib/autonogrow-staging`, fuera del repo/frontend.
- [ ] Google OAuth permite el dominio HTTPS real de staging.
- [ ] Login owner real funciona y solo muestra recursos autorizados.
- [ ] Login business admin real funciona para su negocio y rechaza otro negocio.
- [ ] Login customer real funciona y no muestra reservas de otra cuenta.
- [ ] Cookies verificadas en navegador: Secure, HttpOnly donde corresponde, SameSite=Lax y Path=/.

## Flujos y controles

- [ ] Reserva pública anónima creada correctamente.
- [ ] Reserva autenticada creada y vinculada a la cuenta correcta.
- [ ] Mutación autenticada sin `X-CSRF-Token` devuelve 403.
- [ ] La misma mutación con token válido funciona.
- [ ] CORS rechaza un origen externo no autorizado.
- [ ] Logos y galería cargan desde `/uploads/businesses/...`.
- [ ] El path estático antiguo de adjuntos privados devuelve 404.
- [ ] Adjunto privado sin sesión/token devuelve 401/403.
- [ ] Adjunto privado con owner/admin/customer propietario o booking token correcto funciona.
- [ ] `audit_logs` registra login, cambios sensibles, reservas y media sin tokens/cookies/mensajes completos.

## Smoke test y operación

- [ ] `python scripts/predeploy_check.py` termina con 0 FAIL antes de subir.
- [ ] Servicio detenido y backup DB/uploads/keyring verificado antes de migrar.
- [ ] `python scripts/check_database_migration_state.py` no informa ausencias.
- [ ] Una base heredada completa se marcó con baseline solo mediante confirmación explícita.
- [ ] `alembic upgrade head` terminó y `python scripts/manage_migrations.py validate` devuelve 0.
- [ ] `alembic heads` devuelve únicamente `20260730_02`.
- [ ] `python scripts/smoke_test_staging.py --base-url https://DOMINIO-STAGING` termina con 0 FAIL.
- [ ] Backup local SQLite + uploads creado y verificado.
- [ ] Backup copiado a almacenamiento externo cifrado.
- [ ] Restauración probada en una ruta aislada, sin tocar staging activo.
- [ ] Journald y logs del proxy revisados: sin secretos, tokens ni PII innecesaria.
- [ ] Alertas básicas de disco, 5xx, certificado y backup revisadas.
- [ ] Rollback preparado con versión anterior identificable y backup previo consistente.
- [ ] Incidencias, excepciones y WARN documentados antes de decidir producción.
- [ ] Las 40 pruebas IG-S1 siguen registradas en `docs/pending_final_validation.md`; cada ejecución
  tiene estado, fecha, responsable y evidencia.
- [ ] La matriz `docs/final_release_validation_matrix.md` no contiene bloqueantes pendientes al
  autorizar producción.
