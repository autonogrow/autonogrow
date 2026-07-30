# AutonoGrow backend

El webhook Instagram persiste en una inbox y responde tras commit. Ejecutar el proceso separado con `python -m app.workers.channel_worker`. Arquitectura y operación: `docs/persistent_queue_architecture.md` y `docs/channel_worker_operations.md`.

Backend FastAPI/SQLAlchemy con PostgreSQL oficial en staging/producción, SQLite local y migraciones
Alembic. El driver fijado es psycopg 3. Ejecutar comandos desde la raíz salvo indicación contraria.

```bash
python -m pip install -r backend/requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --app-dir backend --reload
```

Documentación operativa:

- `docs/database_migrations.md`
- `docs/sqlite_operations.md`
- `docs/dependency_management.md`
- `docs/ci_pipeline.md`
- `docs/database_backup_and_restore.md`
- `docs/postgresql_architecture.md`
- `docs/sqlite_to_postgresql_migration.md`
- `docs/postgresql_operations.md`
- `docs/postgresql_backup_restore.md`
- `docs/database_concurrency.md`
- `docs/postgresql_rollback.md`
- `docs/pending_final_validation.md`
- `docs/final_release_validation_matrix.md`

En staging/producción, el servicio solo arranca si la base está en head. No ejecuta upgrade, stamp,
`create_all` ni ALTER manuales. Mantener `DATABASE_MIGRATION_CHECK=true` y
`ENABLE_LEGACY_STARTUP_MIGRATIONS=false`.
# Onboarding de negocios

La API owner dispone de un asistente persistente de 15 pasos, plantillas versionadas, clonación segura, readiness, preview y activación explícita. Aplicar primero Alembic `20260730_05`; después ejecutar `python scripts/seed_onboarding_templates.py` para dry-run y repetir con `--apply`. No hay nuevas variables de entorno ni tareas de startup.
