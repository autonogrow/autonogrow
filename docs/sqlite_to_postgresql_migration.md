# Migración SQLite a PostgreSQL

El migrador exige las tablas legacy de negocio y un PostgreSQL vacío en la única head Alembic. Las
tablas `operational_states` y `backup_records`, introducidas en `20260730_06`, son opcionales solo en
el origen: si existen se copian y validan; si no existen, sus tablas destino permanecen vacías. No se
crean registros sintéticos. `alembic_version` es solo destino y `app_migrations`, si existe en una
SQLite legacy, se ignora. Las columnas nullable `request_id` de inbox/outbox también pueden faltar en
un origen `20260730_05`.

No es reanudable: si detecta una tabla o columna legacy obligatoria ausente, tablas pobladas, destino
parcial, FK inválidas o revisión incorrecta, aborta. Nunca copia `alembic_version`, `app_migrations`,
uploads, entorno ni secretos externos.

## Preparación

1. Detener backend y worker.
2. Registrar versión de código y head Alembic.
3. Ejecutar `PRAGMA integrity_check` y guardar recuentos.
4. Copiar SQLite, uploads y keyring de cifrado a almacenamiento protegido.
5. Crear PostgreSQL vacío, aplicar `alembic upgrade head` y verificar permisos.

Dry-run, sin copiar filas:

```bash
python scripts/migrate_sqlite_to_postgresql.py \
  --source /ruta/snapshot/autonogrow.db \
  --destination-url "$DATABASE_URL" \
  --report migration_report.json
```

Aplicación explícita:

```bash
python scripts/migrate_sqlite_to_postgresql.py \
  --source /ruta/snapshot/autonogrow.db \
  --destination-url "$DATABASE_URL" \
  --apply --report migration_report.json
```

`--upgrade-destination` existe, pero requiere `--apply` y debe usarse solo tras una decisión operativa
expresa; un dry-run es siempre de solo lectura sobre ambas bases. El script
copia en un orden versionado y validado contra las FK, preserva IDs, timestamps, estados, saldos,
idempotencia y ciphertext, resetea secuencias reales, y compara recuentos, PK, nulos y checksums
estructurales. El informe no contiene tokens, ciphertext completo, emails ni mensajes.

Tras aplicar: guardar el informe, ejecutar tests de humo, comprobar la siguiente inserción y mantener
el SQLite original inmutable. Cualquier diferencia es NO-GO y obliga a limpiar/recrear el destino.
