# Despliegue certificado de staging

## Before deploy

- [ ] `git status --short` vacío; SHA/release ID y operador registrados.
- [ ] pytest, Ruff, mypy, `pip check`, Alembic y `predeploy_check.py` sin fallos nuevos.
- [ ] Backup PostgreSQL/uploads conocido y rollback de código/frontend preparado.
- [ ] `/etc/autonogrow/backend.env` parte de la plantilla staging: sin placeholders,
  `APP_ENV=staging`, dominio/origen/rutas exclusivos, metadata del build y modo publishing explícito.
- [ ] `/opt/autonogrow/backend/.venv-next/bin/python -m alembic current` y `... heads` revisados;
  una head `20260822_23`. No downgrade rutinario.

## Deploy

1. Instalar la release identificable en `/opt/autonogrow` sin `git pull` sobre el árbol activo.
2. Instalar el lock en `/opt/autonogrow/backend/.venv-next` y ejecutar
   `/opt/autonogrow/backend/.venv-next/bin/python -m pip check`.
3. Detener workers, obtener backup/pre-check y ejecutar con ese mismo Python
   `scripts/manage_migrations.py upgrade`.
4. Ejecutar `scripts/manage_migrations.py validate` con el mismo runtime antes de arrancar tráfico.
5. Primera adopción del frontend atómico: mover el directorio legacy a una release conservada y
   crear `/var/www/autonogrow` como symlink a ella. Después ejecutar con el SHA:

   ```bash
   sudo RELEASE_ID=SHA SOURCE_ROOT=/opt/autonogrow scripts/publish_frontend.sh
   ```

6. Instalar únicamente las unidades staging de Sprint 10A, sin sobrescribir las unidades existentes
   de backend/channel worker, verificarlas y recargar systemd:

   ```bash
   sudo install -o root -g root -m 0644 deploy/autonogrow-instagram-publisher.service \
     /etc/systemd/system/autonogrow-instagram-publisher.service
   sudo install -o root -g root -m 0644 deploy/autonogrow-maintenance.service \
     /etc/systemd/system/autonogrow-maintenance.service
   sudo install -o root -g root -m 0644 deploy/autonogrow-maintenance.timer \
     /etc/systemd/system/autonogrow-maintenance.timer
   sudo systemd-analyze verify /etc/systemd/system/autonogrow-instagram-publisher.service \
     /etc/systemd/system/autonogrow-maintenance.service \
     /etc/systemd/system/autonogrow-maintenance.timer
   sudo systemctl daemon-reload
   ```

   Estas unidades son específicas del staging actual: usuario `deploy`, runtime
   `/opt/autonogrow/backend/.venv-next` y almacenamiento `/var/lib/agw-staging`. Las demás unidades
   de `deploy/` son referencias genéricas y requieren adaptación antes de instalarlas en otro host.
7. Validar Caddy antes de reload: `sudo caddy validate --config /etc/caddy/Caddyfile`.
8. Reiniciar backend y únicamente el channel worker que ya estuviera autorizado/activo. Confirmar
   los flags de publishing, pero mantener Instagram publisher stopped/disabled y
   `INSTAGRAM_PUBLISHING_WORKER_ENABLED=false`. Habilitar el timer de mantenimiento existente. No
   crear otro scheduler ni activar providers como parte de 10C.
9. `sudo systemctl reload caddy` solo tras una validación correcta.

## After deploy

```bash
curl --fail --silent https://staging.autonogrow.es/health
curl --fail --silent https://staging.autonogrow.es/ready
/opt/autonogrow/backend/.venv-next/bin/python scripts/smoke_test_staging.py \
  --base-url https://staging.autonogrow.es
/opt/autonogrow/backend/.venv-next/bin/python scripts/certify_staging.py \
  --base-url https://staging.autonogrow.es \
  --expected-git-commit SHA --local-system --json-output /tmp/staging-certification.json
/opt/autonogrow/backend/.venv-next/bin/python scripts/check_pilot_configuration.py --json
```

- [ ] `/api/config/build` devuelve `app_env=staging` y el SHA desplegado.
- [ ] `systemctl is-active/is-enabled` coincide con el estado previamente autorizado; `NRestarts`
  sin bucle y publisher stopped/disabled.
- [ ] Capability sanity sin filas ausentes/inconsistentes y readiness revisado para el piloto QA.
- [ ] `/opt/autonogrow/backend/.venv-next/bin/python scripts/run_maintenance.py --json` termina
  como dry-run/rollback.
- [ ] Revisar logs recientes y completar `staging_manual_certification.md`.
- [ ] No declarar `CERTIFIED` mientras haya `FAIL`, `BLOCKER` o gates manuales sin evidencia.
