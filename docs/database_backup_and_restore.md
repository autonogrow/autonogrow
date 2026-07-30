# Backup y restore

Antes de migrar, detener el servicio o usar `scripts/backup_sqlite_uploads.py`, que emplea la API de
backup SQLite. Conservar juntos base, uploads, versión de código, entorno protegido y versión de
revisión Alembic.

```bash
sudo systemctl stop autonogrow
sudo -u autonogrow /opt/autonogrow/.venv/bin/python /opt/autonogrow/scripts/backup_sqlite_uploads.py --output-dir /var/backups/autonogrow --keep 14
sqlite3 /var/backups/autonogrow/autonogrow_TIMESTAMP.sqlite3 "PRAGMA integrity_check;"
unzip -t /var/backups/autonogrow/uploads_TIMESTAMP.zip
sudo systemctl start autonogrow
```

Copiar el juego a almacenamiento externo cifrado y verificar tamaño, checksum, permisos y
propietario. No guardar backups en Git ni en la raíz pública del frontend.

## Restore

1. Detener el servicio y guardar una copia recuperable del estado fallido.
2. Restaurar primero en una ruta aislada y ejecutar `PRAGMA integrity_check;`.
3. Restaurar uploads del mismo juego sin servir adjuntos privados públicamente.
4. Ajustar propietario/grupo y permisos (directorio 0750, ficheros no públicos).
5. Configurar `DATABASE_URL` a la copia restaurada y ejecutar el diagnóstico Alembic.
6. Aplicar únicamente la secuencia documentada en `database_migrations.md`.
7. Arrancar y validar health, login, reservas, conversaciones, integraciones, créditos y logs.

Para rollback tras una migración, preferir el downgrade técnico solo si está documentado como seguro.
Si hay riesgo destructivo, restaurar el juego completo aceptando explícitamente la pérdida de datos
posteriores al backup.

**Advertencia crítica:** un backup de base sin `INTEGRATION_ENCRYPTION_KEYS_JSON` no permite
recuperar los tokens cifrados de integraciones. La keyring real debe conservarse por separado,
cifrada, con acceso restringido y versionado compatible; nunca incluirla en documentación, logs o Git.
