# Plan de despliegue seguro en VPS

## Arquitectura recomendada

```text
Internet :443/:80
       │
    Caddy o Nginx ── frontend estático
       │
       └── /api, /health, /uploads/businesses → 127.0.0.1:8000
                                                    │
                                                 FastAPI
                                                    │
                              /var/lib/autonogrow/{data,uploads}
```

FastAPI debe escuchar solo en `127.0.0.1:8000`. El frontend usa el mismo origen en producción; local conserva `127.0.0.1:8000`. También puede definirse `window.AUTONOGROW_API_BASE_URL` antes de `auth.js` si la API vive en otro origen autorizado.

Los artefactos revisables están en `deploy/backend.env.example`, `deploy/autonogrow.service.example` y `deploy/Caddyfile.example`. El procedimiento operativo completo está en `docs/vps_deploy_runbook.md`.

## Red y TLS

- Abrir 22/tcp solo desde IPs administrativas si es posible, 80/tcp para redirección/ACME y 443/tcp para HTTPS.
- Cerrar 8000, SQLite y cualquier puerto de desarrollo al exterior.
- Obligar HTTP → HTTPS y TLS moderno.
- Configurar el proxy para sobrescribir/preservar correctamente la IP cliente y limitar tamaño de body al máximo permitido.
- Usar Caddy para TLS automático o Nginx con Certbot. En ambos casos, enviar `Host`, `X-Forwarded-Proto` y `X-Forwarded-For` de forma controlada.

Ejemplo conceptual Caddy:

```caddyfile
app.example.com {
    root * /var/www/autonogrow
    @backend path /api/* /health /uploads/businesses/*
    reverse_proxy @backend 127.0.0.1:8000
    file_server
}
```

No mapear `/var/lib/autonogrow/uploads` completo en el servidor web.

## Usuarios, rutas y permisos

- Crear usuario de sistema sin login: `autonogrow`.
- Código: `/opt/autonogrow`, propiedad root y lectura para el servicio.
- Base: `/var/lib/autonogrow/data/autonogrow.db`.
- Uploads: `/var/lib/autonogrow/uploads`.
- Entorno: `/etc/autonogrow/backend.env`, propietario root, grupo del servicio, modo `0640` (o `0600`).
- Backups: `/var/backups/autonogrow`, accesible solo por el usuario encargado; copiar cifrado fuera del VPS.
- Nunca colocar `.env`, DB, adjuntos privados o backups dentro del document root del frontend.

## Variables production

```env
APP_ENV=production
COOKIE_SECURE=true
CSRF_ENABLED=true
RATE_LIMIT_ENABLED=true
SECURITY_HEADERS_ENABLED=true
FRONTEND_ORIGINS=https://app.example.com
SESSION_SECRET=<aleatorio de al menos 32 caracteres>
GOOGLE_CLIENT_ID=<cliente real>
OWNER_ALLOWED_EMAILS=<owners vigentes>
DATABASE_URL=sqlite:////var/lib/autonogrow/data/autonogrow.db
UPLOADS_DIR=/var/lib/autonogrow/uploads
UPLOAD_MAX_SIZE_MB=5
```

Google debe autorizar el dominio HTTPS real. No copiar los placeholders de `.env.example`.

El backend rechaza en production rutas SQLite/uploads relativas, rutas dentro del repo o frontend público, origins HTTP/wildcard/example.com y credenciales placeholder.

## Servicio systemd

Ejemplo base, ajustando la ruta del virtualenv:

```ini
[Unit]
Description=AutonoGrow FastAPI
After=network.target

[Service]
User=autonogrow
Group=autonogrow
WorkingDirectory=/opt/autonogrow/backend
EnvironmentFile=/etc/autonogrow/backend.env
ExecStart=/opt/autonogrow/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure
RestartSec=5
PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/autonogrow

[Install]
WantedBy=multi-user.target
```

Empezar con un solo worker: SQLite y el rate limiter en memoria no ofrecen coordinación multiworker. Revisar límites systemd y rutas antes de activar `ProtectSystem`.

## Logs y backups

- Enviar stdout/stderr a journald, sin tokens ni headers completos.
- Definir límite/retención en journald o logrotate si el proxy escribe ficheros.
- Ejecutar diariamente `scripts/backup_sqlite_uploads.py --output-dir /var/backups/autonogrow --keep 14` como el usuario con permisos.
- Cifrar y replicar los backups fuera del VPS; el script no cifra ni sube copias.
- Mantener 7 diarios, 4 semanales y 3 mensuales en el almacenamiento externo y probar restauración mensualmente.

Ejemplo cron (hora UTC y rutas a ajustar):

```cron
17 2 * * * /opt/autonogrow/.venv/bin/python /opt/autonogrow/scripts/backup_sqlite_uploads.py --output-dir /var/backups/autonogrow --keep 14
```

## Comprobaciones postdeploy

1. Confirmar que 8000 no responde desde Internet y sí desde localhost.
2. Verificar redirección HTTP, certificado, HSTS y security headers.
3. Probar CORS desde el dominio real y rechazo desde otro origen.
4. Revisar cookies Secure/HttpOnly/SameSite y CSRF con/sin header.
5. Probar login Google, owner, business A/B, customer A/B y reserva anónima.
6. Confirmar que logos/galería cargan y un path antiguo de adjunto bajo `/uploads/...` devuelve 404.
7. Superar un límite controlado y comprobar 429 sin bloquear tráfico normal.
8. Crear una acción sensible y verificar `audit_logs` sin token/cookie.
9. Ejecutar backup, restaurarlo en un directorio aislado y revisar DB/uploads.
10. Revisar permisos, firewall, journald/proxy logs y monitorización de disco/certificado.

## Pendiente antes de tráfico real

- Monitorización y alertas de disponibilidad, disco, backups, 5xx y certificados.
- Destino externo cifrado para backups.
- Política RGPD/retención y respuesta a incidentes.
- Rate limiting compartido y PostgreSQL antes de escalar a varios procesos/servidores.
