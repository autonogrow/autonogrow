# Migraciones de base de datos

La head vigente es `20260730_06`. Añade estado operativo, metadatos de backup y `request_id` nullable en inbox/outbox; baja a `20260730_05` solo con servicio detenido, backup verificado y código compatible.

La head actual es `20260730_04` y depende de `20260730_03`. Añade checks de créditos y reservas e
índices para comprobar solapamientos. Funciona en SQLite y PostgreSQL. Su ciclo técnico es `upgrade
head`, `downgrade 20260730_03`, `upgrade head`, siempre con backend y worker detenidos.

Alembic es la fuente oficial del esquema. La metadata se registra de forma explícita en
`backend/app/models/registry.py`; `alembic/env.py` carga ese registro y obtiene la URL mediante
`Settings`. Nunca se imprime la URL completa.

## Revisiones

- `20260730_01`: baseline del esquema actual completo. Crea bases nuevas y no debe ejecutarse
  sobre una base heredada. Su downgrade aborta porque eliminar el esquema completo perdería datos.
- `20260730_02`: añade el índice técnico reversible
  `ix_conversation_messages_timeline`. Es la head inicial del sistema oficial.
- `20260730_03`: crea inbox, outbox y heartbeat persistentes.
- `20260730_04`: añade constraints e índices para concurrencia PostgreSQL.

Solo debe existir una head. Comprobar con `alembic heads` y `alembic history`.

## Matriz por tipo de base

| Tipo | Diagnóstico | Acción segura |
|---|---|---|
| Nueva/vacía | Sin tablas de negocio | `alembic upgrade head` |
| Heredada completa | Tablas actuales, sin `alembic_version`, sin ausencias | Backup, `stamp 20260730_01`, después `upgrade head` |
| Heredada incompleta | Faltan tablas o columnas críticas | Revisión manual; no hacer stamp |
| Test | Fichero temporal sin datos reales | `alembic upgrade head`; eliminar al terminar |
| Staging | Siempre copia/backup verificado antes | Diagnóstico, stamp explícito si procede, upgrade y validación |

No se hace stamp ni upgrade durante el arranque. Una base sin `alembic_version` nunca se considera
vacía automáticamente.

## Comandos

Desde la raíz, con el entorno del destino cargado y el servicio detenido:

```bash
python scripts/check_database_migration_state.py
alembic current
alembic heads
alembic history
```

Base nueva:

```bash
alembic upgrade head
python scripts/manage_migrations.py validate
```

Base heredada completa, tras backup e inspección del diagnóstico:

```bash
python scripts/manage_migrations.py stamp-baseline --confirm STAMP-BASELINE
alembic upgrade head
python scripts/manage_migrations.py validate
```

El wrapper rechaza stamp sin confirmación, sobre base vacía, incompleta o ya versionada.

## Staging: secuencia exacta

```bash
sudo systemctl stop autonogrow
sudo -u autonogrow /opt/autonogrow/.venv/bin/python /opt/autonogrow/scripts/backup_sqlite_uploads.py --output-dir /var/backups/autonogrow --keep 14
sudo -u autonogrow bash -c 'set -a; source /etc/autonogrow/backend.env; set +a; cd /opt/autonogrow; .venv/bin/python scripts/check_database_migration_state.py'
sudo -u autonogrow bash -c 'set -a; source /etc/autonogrow/backend.env; set +a; cd /opt/autonogrow; .venv/bin/python scripts/manage_migrations.py stamp-baseline --confirm STAMP-BASELINE'
sudo -u autonogrow bash -c 'set -a; source /etc/autonogrow/backend.env; set +a; cd /opt/autonogrow; .venv/bin/alembic upgrade head'
sudo -u autonogrow bash -c 'set -a; source /etc/autonogrow/backend.env; set +a; cd /opt/autonogrow; .venv/bin/python scripts/manage_migrations.py validate'
sudo systemctl start autonogrow
```

Omitir `stamp-baseline` si `alembic current` ya devuelve una revisión. Si el diagnóstico no dice
literalmente `stamp baseline`, detenerse y revisar. No ejecutar estos comandos en este sprint sobre
staging real.

## Rollback técnico

`20260730_04` puede revertirse hasta `20260730_03`, con servicio detenido y backup:

```bash
alembic downgrade 20260730_03
alembic current
```

La aplicación configurada con `DATABASE_MIGRATION_CHECK=true` no arrancará estando detrás de head;
un rollback exige desplegar a la vez el código anterior. No ejecutar downgrade de la baseline:
falla deliberadamente. Para volver atrás desde la baseline, restaurar un backup completo.

## Destino de migraciones legacy

| Lógica anterior | Clasificación | Destino |
|---|---|---|
| ALTER de bookings, staff, branding, incidencias, conversaciones y periodos | Representada en baseline | Obsoleta tras stamp |
| Índices únicos de integraciones | Representada en baseline | Obsoleta tras stamp |
| Apertura de wallets y periodos | Backfill de datos | Ventana legacy explícita o comando administrativo futuro |
| Asignación inicial de servicios a profesionales | Backfill de datos | Ventana legacy explícita o comando administrativo futuro |
| Migración de variables globales Instagram | Reparación/migración de datos | Solo transición explícita; retirar tras validación funcional |
| `app_migrations` | Marcador histórico manual | Se conserva; Alembic usa `alembic_version` |

`run_lightweight_migrations()` queda deprecado y solo se ejecuta local/test si
`ENABLE_LEGACY_STARTUP_MIGRATIONS=true`. Nunca se mezcla en el mismo arranque con Alembic.
# Onboarding 20260730_05

La revisión `20260730_05` sucede a `20260730_04`, conserva negocios activos, transforma `inactive` en `suspended` y crea sesiones, plantillas y perfiles/asignaciones de personal. Debe aplicarse con Alembic antes del seed; FastAPI no ejecuta upgrade, stamp ni DDL al arrancar. Véase [business_onboarding_operations.md](business_onboarding_operations.md).
