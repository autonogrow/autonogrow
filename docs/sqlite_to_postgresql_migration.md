# Migración SQLite a PostgreSQL

La primera versión exige un origen SQLite con el esquema completo y un PostgreSQL vacío en la única
head Alembic. No es reanudable: si detecta tablas pobladas, destino parcial, FK inválidas o revisión
incorrecta, aborta. Nunca copia `alembic_version`, uploads, entorno ni secretos externos.

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

`--upgrade-destination` existe, pero debe usarse solo tras una decisión operativa expresa. El script
copia en un orden versionado y validado contra las FK, preserva IDs, timestamps, estados, saldos,
idempotencia y ciphertext, resetea secuencias reales, y compara recuentos, PK, nulos y checksums
estructurales. El informe no contiene tokens, ciphertext completo, emails ni mensajes.

Tras aplicar: guardar el informe, ejecutar tests de humo, comprobar la siguiente inserción y mantener
el SQLite original inmutable. Cualquier diferencia es NO-GO y obliga a limpiar/recrear el destino.
