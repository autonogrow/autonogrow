# Despliegue certificado de staging

## Before deploy

- [ ] `git status --short` vacío; SHA/release ID y operador registrados.
- [ ] pytest, Ruff, mypy, `pip check`, Alembic y `predeploy_check.py` sin fallos nuevos.
- [ ] Backup PostgreSQL/uploads conocido y rollback de código/frontend preparado.
- [ ] `/etc/autonogrow/backend.env` parte de la plantilla staging: sin placeholders,
  `APP_ENV=staging`, dominio/origen/rutas exclusivos, metadata del build y modo publishing explícito.
- [ ] `alembic current` y `alembic heads` revisados; una head `20260814_19`. No downgrade.

## Deploy

1. Instalar la release identificable en `/opt/autonogrow` sin `git pull` sobre el árbol activo.
2. Instalar el lock en `/opt/autonogrow/.venv` y ejecutar `python -m pip check`.
3. Detener workers, obtener backup/pre-check y ejecutar `python scripts/manage_migrations.py upgrade`.
4. Ejecutar `python scripts/manage_migrations.py validate` antes de arrancar tráfico.
5. Primera adopción del frontend atómico: mover el directorio legacy a una release conservada y
   crear `/var/www/autonogrow` como symlink a ella. Después ejecutar con el SHA:

   ```bash
   sudo RELEASE_ID=SHA SOURCE_ROOT=/opt/autonogrow scripts/publish_frontend.sh
   ```

6. Instalar/actualizar unidades versionadas y ejecutar `sudo systemctl daemon-reload`.
7. Validar Caddy antes de reload: `sudo caddy validate --config /etc/caddy/Caddyfile`.
8. Reiniciar backend, channel worker e Instagram publisher; habilitar el timer de mantenimiento
   existente. No crear otro scheduler.
9. `sudo systemctl reload caddy` solo tras una validación correcta.

## After deploy

```bash
curl --fail --silent https://staging.autonogrow.es/health
curl --fail --silent https://staging.autonogrow.es/ready
python scripts/smoke_test_staging.py --base-url https://staging.autonogrow.es
python scripts/certify_staging.py --base-url https://staging.autonogrow.es \
  --expected-git-commit SHA --local-system --json-output /tmp/staging-certification.json
```

- [ ] `/api/config/build` devuelve `app_env=staging` y el SHA desplegado.
- [ ] `systemctl is-active/is-enabled` correcto para backend/workers/timer; `NRestarts` sin bucle.
- [ ] `python -m app.workers.instagram_publish_worker --check` pasa sin reclamar jobs.
- [ ] `python scripts/run_maintenance.py --json` termina como dry-run/rollback.
- [ ] Revisar logs recientes y completar `staging_manual_certification.md`.
- [ ] No declarar `CERTIFIED` mientras haya `FAIL`, `BLOCKER` o gates manuales sin evidencia.
