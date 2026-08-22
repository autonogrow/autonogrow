# Certificación de staging

## Alcance y estado auditado el 14-08-2026

`https://staging.autonogrow.es` es preproducción, no producción. La comprobación externa previa a
Sprint 10A confirmó `/health`, autenticación anónima, páginas legales y headers básicos (12 PASS),
pero el despliegue se declaraba `APP_ENV=production`, no publicaba SHA y exponía `Server: uvicorn`.
Esos tres puntos impiden certificar la release actual. Hay que desplegar este sprint con
`APP_ENV=staging`, metadata real y la plantilla Caddy actualizada. 10C no vuelve a comprobar el host:
esa evidencia sigue pendiente hasta el deploy explícito.

Topología versionada:

| Componente | Servicio/ruta | Conectividad o almacenamiento |
| --- | --- | --- |
| Caddy | 80/443 públicos | frontend `/var/www/autonogrow` y log `/var/log/caddy/autonogrow-access.log` |
| FastAPI | `autonogrow.service` | `127.0.0.1:8000`, `/health`, `/ready`, `/api/config/build` |
| PostgreSQL | servicio del host | DSN en `/etc/autonogrow/backend.env`; driver `psycopg` |
| Colas de canales | `autonogrow-worker.service` | proceso y DB separados del backend |
| Publicación Instagram | `autonogrow-instagram-publisher.service` | proceso y DB separados; modo env explícito |
| Mantenimiento | `autonogrow-maintenance.timer` | una ejecución diaria 04:30 más hasta 10 min de jitter; no existe segundo scheduler |
| Uploads | backend/Caddy | `/var/lib/agw-staging/uploads` |
| Dependencias externas | Google/Meta/SMTP | configuración y secretos solo en environment del host |

Head Alembic esperado: `20260822_23`, una sola head. El frontend anterior se copiaba directorio a
directorio y podía quedar a medias. `publish_frontend.sh` ahora prepara una release completa y
cambia un symlink atómicamente; la migración inicial del directorio legacy se hace una sola vez.
Durante QA 10C el publisher debe permanecer stopped/disabled aunque su unidad esté instalada.

## Gate automatizado

Desde cualquier máquina externa:

```bash
python scripts/certify_staging.py \
  --base-url https://staging.autonogrow.es \
  --expected-git-commit SHA_ESPERADO \
  --json-output staging-certification.json
```

En el VPS, con el venv y environment del servicio cargados de forma segura:

```bash
cd /opt/autonogrow
/opt/autonogrow/backend/.venv-next/bin/python scripts/certify_staging.py \
  --base-url https://staging.autonogrow.es \
  --expected-git-commit SHA_ESPERADO \
  --local-system --json-output /tmp/staging-certification.json
```

`BLOCKER` impide promover, `FAIL` debe corregirse, `WARN` exige decisión registrada,
`MANUAL_REQUIRED` no cambia el exit code, y `PASS` aporta evidencia. Cualquier `FAIL/BLOCKER`
produce exit distinto de cero. El JSON no contiene cookies, tokens, DSN ni URLs firmadas.

Para challenges/asset efímeros se pueden inyectar solo al proceso:

```bash
AUTONOGROW_CERT_META_VERIFY_TOKEN='...' \
AUTONOGROW_CERT_SIGNED_MEDIA_URL='https://staging.autonogrow.es/api/public/instagram-assets/...' \
python scripts/certify_staging.py --base-url https://staging.autonogrow.es
```

No guardar esas variables en shell history, logs o el JSON. La certificación prueba URL válida,
MIME JPEG, firma alterada y expiración, pero nunca imprime la URL.

## Configuración

- Required: `APP_ENV`, metadata de release/SHA, `DATABASE_URL`, `SESSION_SECRET`, origen frontend,
  Google client ID, owner allowlist, directorio uploads y controles cookie/CSRF/rate/security.
- Required al activar Meta real: app ID/secret, verify token, keyring cifrado, modo `meta`, ack
  explícito, worker habilitado, dominio/secret/TTL de asset y timeouts coherentes.
- Feature flags: workers, onboarding/login Instagram, WhatsApp, publishing mode, métricas, alertas y
  backups. Ninguna activa publicación real implícitamente.
- Optional: SMTP/alertas/métricas/backups si su feature flag está apagado.
- Secrets: sesión, DB, Meta/WhatsApp, keyring, signing, SMTP y tokens operativos. Nunca Git.

`Settings` hace fail-fast para entornos gestionados y para combinaciones Meta inseguras. El modo se
consulta en `/api/config/build` y en el preflight. Cambiar `INSTAGRAM_PUBLISHING_MODE` requiere editar
el environment protegido y reiniciar el worker; volver a `simulated` usa el mismo procedimiento.

## Preflight Meta sin publicación

```bash
cd /opt/autonogrow
/opt/autonogrow/backend/.venv-next/bin/python scripts/instagram_publication_preflight.py \
  --business-id ID --content-id ID --json
```

Valida tenant, versión actual aprobada, formato/assets/archivos, servicio, integración, health,
cuenta profesional, scope, token cifrado y construcción de URL firmada. Solo devuelve presencia y
hostname, nunca credenciales ni la URL. El worker ofrece además `python -m
app.workers.instagram_publish_worker --check`; conecta a DB sin reclamar jobs. `--once` sí puede
procesar jobs aprobados pendientes y se usa únicamente en una ventana controlada.

## Separación obligatoria

Staging usa `staging.autonogrow.es`, datos ficticios, cuentas controladas y recursos reiniciables.
Producción usa `autonogrow.es`, datos de pilotos y DB, secrets, uploads, workers y backups distintos.
Nunca compartir `DATABASE_URL`, session/signing secrets ni copiar datos reales sin anonimización
explícita. Las cookies actuales no definen `Domain` y por tanto son host-scoped. CORS de staging
solo admite el origen HTTPS de staging. Las URLs firmadas de staging apuntan exclusivamente a
staging. Admin/Owner muestran `STAGING` solo cuando el backend declara ese entorno.

## Backup y almacenamiento

La certificación comprueba conectividad, dialecto, pool, uploads y mínimo de disco. La estrategia
completa pertenece a Sprint 10B. Hasta disponer de evidencia de backup/restore reciente, registrar
esa ausencia como deuda bloqueante para producción. No copiar un dump de producción a staging.
