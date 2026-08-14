# Procedimiento de despliegue

Usar releases identificables; `deploy_release.py` genera el plan y no hace `git pull`. El orden es:
árbol limpio y validaciones, metadata/GO-NO-GO, disco y backup, mantenimiento, detener workers,
instalar lock, revisar current/head, migrar hacia delante, validar head, cambiar código, publicar el
frontend completo mediante symlink atómico, backend/readiness, workers, smoke/certification, logs y
salir de mantenimiento.

El environment vive en `/etc/autonogrow/backend.env` con modo 0600. `APP_RELEASE_ID`,
`APP_GIT_COMMIT` y `APP_BUILD_TIME` se fijan al construir/desplegar. Reiniciar es obligatorio tras
cambiarlo. Staging y producción usan hosts, DB, secrets, uploads, workers y backups independientes.
Seguir la secuencia ejecutable de `staging_deploy_checklist.md` y registrar cada comando/status.

```text
local/dev
    ↓
staging.autonogrow.es (datos ficticios, controlado y reseteable)
    ↓
certification
    ↓
autonogrow.es (pilotos/datos reales e infraestructura independiente)
```
