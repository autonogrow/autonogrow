# Despliegue de 10C a staging para QA de pilotos

Este procedimiento prepara `staging.autonogrow.es`; no autoriza producción ni llamadas reales a
providers. Ejecutarlo solo en una ventana acordada, con el SHA de 10C revisado y un operador capaz
de restaurar PostgreSQL y uploads. Los comandos son deliberadamente explícitos: no usar `git pull`
sobre la release activa ni copiar secretos al repositorio.

## 1. Preflight y backup

1. Registrar operador, UTC, SHA objetivo y release activa (`readlink -f /opt/autonogrow` y
   `/api/config/build`). Confirmar árbol limpio y que el SHA objetivo pertenece a `main`.
2. Confirmar espacio, PostgreSQL, uploads y estado de servicios. Ejecutar el predeploy con el
   entorno protegido, sin imprimirlo.
3. Crear un backup set coherente de PostgreSQL y uploads con `scripts/run_backup_set.py`; verificarlo
   con `scripts/verify_backup.py` y guardar fuera de la release. No continuar sin una copia
   identificada y restaurable. La evidencia debe incluir manifiesto, checksums y keyring aplicable.
4. Mantener `INSTAGRAM_PROVIDER_ENABLED=false`, `INSTAGRAM_PUBLISHING_WORKER_ENABLED=false`,
   `INSTAGRAM_PUBLISHING_MODE=simulated`, `INSTAGRAM_REAL_PUBLISHING_ACKNOWLEDGED=false`,
   `WHATSAPP_WEBHOOK_ENABLED=false` y `WHATSAPP_EMBEDDED_SIGNUP_ENABLED=false`. No iniciar el
   publisher. No cambiar el estado del channel worker como parte de 10C.

## 2. Preparar release y dependencias

```bash
cd /opt/autonogrow-repository
git fetch --prune origin
git checkout --detach EXPECTED_10C_SHA
git status --short
python3 -m venv /opt/autonogrow/backend/.venv-next
/opt/autonogrow/backend/.venv-next/bin/python -m pip install --require-hashes -r requirements.lock
/opt/autonogrow/backend/.venv-next/bin/python -m pip check
```

Verificar el SHA con `git rev-parse HEAD`; `git status --short` debe estar vacío. Si el mecanismo
real usa un artefacto inmutable en vez del checkout compartido, conservar la misma identidad de
release y no mutar el directorio servido.

## 3. Migración

1. Detener únicamente los procesos que puedan escribir durante la migración conforme al runbook
   vigente; no arrancar procesos que ya estuvieran deshabilitados.
2. Con `DATABASE_URL` tomado de `/etc/autonogrow/backend.env`, ejecutar:

```bash
/opt/autonogrow/backend/.venv-next/bin/python scripts/manage_migrations.py validate
/opt/autonogrow/backend/.venv-next/bin/python scripts/manage_migrations.py upgrade
/opt/autonogrow/backend/.venv-next/bin/python -m alembic current
/opt/autonogrow/backend/.venv-next/bin/python -m alembic heads
```

La única head esperada es `20260822_23`. La migración crea módulos/baseline y materializa los tres
módulos activos para negocios previos. No usar downgrade como rollback rutinario con datos reales.

## 4. Frontend atómico y backend

1. Publicar los frontends con el script existente y el SHA como release ID:

   ```bash
   sudo RELEASE_ID=EXPECTED_10C_SHA SOURCE_ROOT=/opt/autonogrow scripts/publish_frontend.sh
   ```

2. Verificar que `/var/www/autonogrow` es un symlink atómico a la nueva release y conservar la
   release anterior.
3. Validar Caddy antes del reload: `sudo caddy validate --config /etc/caddy/Caddyfile`.
4. Reiniciar el backend y solo los workers que ya estuvieran autorizados/activos antes del deploy.
   Mantener `autonogrow-instagram-publisher.service` stopped/disabled y no habilitar providers.
5. Recargar Caddy después de todas las validaciones locales.

## 5. Health, smoke y sanity de piloto

```bash
curl --fail --silent https://staging.autonogrow.es/health
curl --fail --silent https://staging.autonogrow.es/ready
curl --fail --silent https://staging.autonogrow.es/api/config/build
/opt/autonogrow/backend/.venv-next/bin/python scripts/smoke_test_staging.py \
  --base-url https://staging.autonogrow.es
/opt/autonogrow/backend/.venv-next/bin/python scripts/check_pilot_configuration.py --json
```

- `/api/config/build` debe exponer `app_env=staging` y el SHA objetivo, nunca secretos.
- El sanity de capabilities no debe mostrar filas ausentes, Essential apagado ni `active` sin
  entitlement. Revisar por ID de business, sin datos personales.
- El sanity de readiness debe mostrar blockers y warnings por business. Para el business que se
  usará en QA, aceptar de forma explícita cualquier deuda y confirmar `booking_ready`/`pilot_ready`.
- Ejecutar `scripts/certify_staging.py` y completar `staging_manual_certification.md`. Revisar logs,
  `NRestarts`, migración y backup. No llamar endpoints OAuth/webhook/provider reales.

## 6. Rollback

**Frontend:** cambiar atómicamente `/var/www/autonogrow` a la release anterior comprobada, validar y
recargar Caddy. Esto no revierte backend ni esquema.

**Código backend:** detener tráfico mutante si hace falta, seleccionar la release anterior compatible,
restaurar su entorno inmutable, reiniciar backend y repetir health/build/smoke. Un rollback de código
solo es válido si esa versión puede operar sobre la schema `20260822_23`.

**Schema/datos:** no ejecutar `alembic downgrade` de forma automática tras recibir datos piloto. Si
la versión anterior no es compatible, elegir un forward-fix. Si existe corrupción o se necesita
volver a un punto temporal, activar mantenimiento y seguir `postgresql_backup_restore.md`: restaurar
PostgreSQL y uploads del mismo backup set primero en un entorno aislado, validar, y solo después
cambiar tráfico con aprobación explícita. Esto es recuperación de datos/schema, no rollback de código.

Abortar y volver a la release anterior ante migración divergente, health/readiness fallido, aislamiento
tenant dudoso, build incorrecto o incapacidad para demostrar backup restaurable. Una integración
opcional desconectada es deuda documentable; booking roto o capabilities sin enforcement es blocker.

