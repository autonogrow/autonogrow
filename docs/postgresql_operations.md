# Operación PostgreSQL

Variables mínimas: `DATABASE_URL`, `ALLOW_SQLITE_IN_PRODUCTION=false`, pool 5+5, timeouts documentados,
`DATABASE_APPLICATION_NAME` por entorno y `WORKER_CONCURRENCY_MODE=single` inicialmente. PostgreSQL
permite `multi`; SQLite lo rechaza.

Antes de arrancar: `alembic current`, `alembic heads` y
`python scripts/manage_migrations.py validate`. FastAPI no crea, altera, actualiza ni estampa el
esquema. Arrancar backend y después worker. Parar en orden inverso.

Vigilar conexiones checked out, overflow, timeouts, deadlocks, locks, espacio, WAL, latencia y
heartbeats. Los errores se clasifican sin SQL ni parámetros. Un aumento sostenido de pool timeout o
deadlock es incidente; no ampliar el pool sin calcular conexiones totales de backend, workers,
migraciones y administración.

Para desarrollo local instalado: crear usuario/base exclusivos, restringir escucha a localhost,
usar una contraseña no reutilizada y aplicar el lock de dependencias. No usar el contenedor de
desarrollo ni su volumen como backup productivo.
