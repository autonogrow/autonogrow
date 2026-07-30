# Arquitectura PostgreSQL

PostgreSQL 16 es la base oficial de staging y producción. FastAPI y cada proceso worker crean su
propio `Engine` y sus propias sesiones; nunca comparten una `Session`. SQLite queda limitado a
desarrollo local, tests rápidos y diagnóstico, siempre con un único worker.

La URL oficial usa `postgresql+psycopg://`. El engine trabaja en `READ COMMITTED`, con `pre_ping`,
pool acotado, reciclado y timeouts de conexión, sentencia, lock y transacción inactiva. No se usa
`SERIALIZABLE` global: wallets, reservas e integraciones se protegen con locks de fila, restricciones
e idempotencia. Inbox y outbox usan `FOR UPDATE SKIP LOCKED` en PostgreSQL.

`DATABASE_URL` nunca se registra completa. `sanitize_database_url()` oculta usuario, contraseña y
query. El estado owner publica solo dialecto, métricas del pool, categorías de error y workers sin
hostname. El health público permanece mínimo.

Para desarrollo se puede ejecutar `docker compose -f deploy/docker-compose.postgresql.yml up -d`
o instalar PostgreSQL 16 localmente, crear una base no productiva y aplicar `alembic upgrade head`.
La contraseña del compose es solo de desarrollo y el puerto escucha en localhost.

Deuda explícita: buena parte del esquema histórico usa fechas UTC naive. Este sprint no hace una
conversión masiva arriesgada; los campos nuevos conservan compatibilidad y la normalización completa
a `DateTime(timezone=True)` requiere una migración de datos separada.
