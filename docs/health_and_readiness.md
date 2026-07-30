# Liveness y readiness

`GET /health` siempre responde `{"status":"ok"}` si el proceso puede atender HTTP. No consulta DB, disco, migraciones, claves ni proveedores.

`GET /ready` comprueba consulta SQL simple, head Alembic única, keyring cuando procede, escritura en uploads, espacio mínimo y ausencia de mantenimiento. Devuelve solo `ready` (200) o `not_ready` (503). Nunca llama a Meta, Google ni SMTP. Ajustar `READINESS_TIMEOUT_SECONDS` y `READINESS_MIN_DISK_FREE_BYTES` con valores conservadores.
