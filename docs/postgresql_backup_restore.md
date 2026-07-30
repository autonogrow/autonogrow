# Backup y restore PostgreSQL

La automatización usa `run_backup_set.py`, manifests SHA-256 y restore solo en `autonogrow_restore_*`. Véanse `postgresql_backup_automation.md`, `backup_verification.md` y `restore_testing.md`; el keyring se conserva cifrado por separado.

Usar formato custom y no poner contraseñas en la línea de comandos. Preferir `.pgpass` con permisos
0600, prompt o variable temporal protegida.

```bash
pg_dump -Fc --no-owner --file autonogrow_YYYYMMDD.dump "$DATABASE_URL"
pg_restore --list autonogrow_YYYYMMDD.dump > autonogrow_YYYYMMDD.contents
```

El backup de base no sustituye el de uploads ni el del keyring. Guardar los tres con versión de
código, head Alembic, checksums, recuentos, fecha y responsable. Cifrar y copiar fuera del servidor.

Restaurar siempre primero en una base aislada vacía:

```bash
createdb autonogrow_restore_test
pg_restore --clean --if-exists --no-owner --dbname autonogrow_restore_test autonogrow_YYYYMMDD.dump
```

Después validar head, FK, recuentos, saldos, ciphertext por presencia/longitud/igualdad, secuencias y
smoke tests. No ejecutar `--clean` contra la base activa. Una restauración productiva exige parada de
backend/worker, aprobación, ventana registrada y decisión explícita sobre pérdida de escrituras.
