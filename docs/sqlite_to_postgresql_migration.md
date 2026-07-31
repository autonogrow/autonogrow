# Migración SQLite a PostgreSQL

El migrador exige las 29 tablas de negocio de la baseline `20260730_01` y un PostgreSQL vacío en la
única head Alembic. Son opcionales solo en el origen las tablas añadidas después de esa baseline:
`webhook_inbox_events`, `channel_outbox_messages`, `worker_heartbeats`, las cuatro tablas de
onboarding/perfiles, `operational_states` y `backup_records`. Si existen se copian y validan; si no
existen, sus tablas destino permanecen vacías. No se crean registros sintéticos.

Una fuente baseline puede omitir las columnas añadidas por `20260730_05` en `businesses`, `services`
y `availability_settings`. Solo se aceptan los NULL y defaults declarados por esa revisión (ES,
español, Europe/Madrid, EUR, flags y buffers documentados). El estado legacy `inactive` se convierte
explícitamente en `suspended`, como hizo Alembic; cualquier otro estado desconocido bloquea la copia.
Las columnas nullable `request_id` de inbox/outbox pueden faltar en fuentes anteriores a
`20260730_06`. Cada omisión, default y transformación prevista aparece en el informe.

`alembic_version` es solo destino y `app_migrations`, si existe en SQLite, se ignora. El informe se
escribe también si el análisis encuentra tablas obligatorias ausentes o columnas incompatibles, antes
de abrir una transacción de copia.

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

El checksum estructural selecciona PK y FK desde `Base.metadata`, añade las columnas críticas y las
ordena por nombre. Intersecta ese contrato con las columnas físicas de la fuente, excluyendo de forma
simétrica únicamente las ausencias legacy permitidas. Cada fila se serializa como pares
`[nombre_columna, valor_normalizado]`; por ello no depende del orden físico ni de que SQLite refleje
las mismas constraints FK que PostgreSQL.

Tras aplicar: guardar el informe, ejecutar tests de humo, comprobar la siguiente inserción y mantener
el SQLite original inmutable. Cualquier diferencia es NO-GO y obliga a limpiar/recrear el destino.
