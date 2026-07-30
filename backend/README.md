# AutonoGrow backend

Backend FastAPI/SQLAlchemy con SQLite y migraciones oficiales Alembic. Ejecutar comandos desde la
raíz del repositorio salvo indicación contraria.

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
- `docs/pending_final_validation.md`
- `docs/final_release_validation_matrix.md`

En staging/producción, el servicio solo arranca si la base está en head. No ejecuta upgrade, stamp,
`create_all` ni ALTER manuales. Mantener `DATABASE_MIGRATION_CHECK=true` y
`ENABLE_LEGACY_STARTUP_MIGRATIONS=false`.
