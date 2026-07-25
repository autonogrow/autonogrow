# Runbook de despliegue VPS

Este runbook prepara un despliegue inicial de un solo worker con SQLite. Sustituir `app.example.com`, IPs y rutas indicadas antes de ejecutar. Probar primero en un VPS de staging o snapshot recuperable.

## 1. Preparación local

Desde la raíz del repositorio:

```powershell
.venv\Scripts\python.exe scripts\predeploy_check.py
cd backend
..\.venv\Scripts\python.exe -m compileall app
..\.venv\Scripts\python.exe -m app.seed
```

No continuar con ningún FAIL. Los WARN sobre ausencia de `.env` real son esperados en el repo.

## 2. Usuario y carpetas

En el VPS, como root o mediante `sudo`:

```bash
sudo useradd --system --home /var/lib/autonogrow --shell /usr/sbin/nologin autonogrow
sudo install -d -o root -g autonogrow -m 0750 /opt/autonogrow
sudo install -d -o autonogrow -g autonogrow -m 0750 /var/lib/autonogrow/data
sudo install -d -o autonogrow -g autonogrow -m 0750 /var/lib/autonogrow/uploads
sudo install -d -o autonogrow -g autonogrow -m 0750 /var/backups/autonogrow
sudo install -d -o root -g autonogrow -m 0750 /etc/autonogrow
sudo install -d -o root -g root -m 0755 /var/www/autonogrow
```

Si el usuario ya existe, `useradd` fallará de forma inocua: comprobar su uid/grupo en vez de recrearlo. No usar permisos `0777`.

## 3. Copiar código y frontend

Copiar una versión identificable del repositorio a `/opt/autonogrow` mediante el mecanismo de despliegue elegido. No copiar `.env`, backups, DB local ni caches. El código debe ser escribible por root/despliegue, no por el proceso web.

Copiar a `/var/www/autonogrow` únicamente el contenido estático necesario para conservar las rutas relativas entre:

- `autonogrow-admin`;
- `autonogrow-owner`;
- `autonogrow-customer`;
- `autonogrow-landing`;
- `autonogrow-shared`;
- `privacy`;
- `data-deletion`.

El frontend detecta production y usa `window.location.origin`. No es necesario editar los JS si proxy y frontend comparten dominio.

Para publicar o actualizar únicamente las páginas legales desde una copia ya situada en
`/opt/autonogrow`, usar:

```bash
sudo install -d -o root -g root -m 0755 /var/www/autonogrow/privacy
sudo install -d -o root -g root -m 0755 /var/www/autonogrow/data-deletion
sudo install -d -o root -g root -m 0755 /var/www/autonogrow/autonogrow-shared
sudo install -o root -g root -m 0644 /opt/autonogrow/privacy/index.html /var/www/autonogrow/privacy/index.html
sudo install -o root -g root -m 0644 /opt/autonogrow/data-deletion/index.html /var/www/autonogrow/data-deletion/index.html
sudo install -o root -g root -m 0644 /opt/autonogrow/autonogrow-shared/legal.css /var/www/autonogrow/autonogrow-shared/legal.css
curl -fsS https://staging.autonogrow.es/privacy/ > /dev/null
curl -fsS https://staging.autonogrow.es/data-deletion/ > /dev/null
```

Estas páginas reutilizan además `autonogrow-landing/styles.css`, que debe conservarse en la raíz
estática como el resto del frontend existente. No requieren reiniciar FastAPI ni recargar Caddy.

## 4. Virtualenv y dependencias

```bash
cd /opt/autonogrow
sudo python3 -m venv .venv
sudo .venv/bin/python -m pip install --upgrade pip
sudo .venv/bin/python -m pip install -r backend/requirements.txt
sudo .venv/bin/python -m pip check
sudo .venv/bin/python -m compileall backend/app
```

Aplicar ownership de lectura acorde al modelo de despliegue. No ejecutar Uvicorn como root.

## 5. Entorno production

En el primer despliegue crear el fichero desde la plantilla. Si `/etc/autonogrow/backend.env` ya existe, no ejecutar el `cp`: conservarlo, hacer una copia protegida y editar solo las variables necesarias.

```bash
sudo cp /opt/autonogrow/deploy/backend.env.example /etc/autonogrow/backend.env
sudo chown root:autonogrow /etc/autonogrow/backend.env
sudo chmod 0640 /etc/autonogrow/backend.env
sudoedit /etc/autonogrow/backend.env
```

Reemplazar dominio, secret, Google client id y owners. Generar `SESSION_SECRET` con un generador criptográfico y no pegarlo en tickets/logs. Mantener:

```env
DATABASE_URL=sqlite:////var/lib/autonogrow/data/autonogrow.db
UPLOADS_DIR=/var/lib/autonogrow/uploads
```

Validar la configuración sin imprimirla:

```bash
sudo -u autonogrow bash -c 'set -a; source /etc/autonogrow/backend.env; set +a; cd /opt/autonogrow/backend; ../.venv/bin/python -c "from app.main import app; print(len(app.openapi()[\"paths\"]))"'
```

Si falla, revisar nombres y permisos; no volcar `env` a consola.

## 6. Google OAuth

En Google Cloud configurar el cliente web real:

- origen JavaScript autorizado: `https://app.example.com`;
- dominio de producción verificado según las exigencias de Google;
- pantalla de consentimiento y cuentas de prueba/producción correctas.

Copiar únicamente el client id público a `GOOGLE_CLIENT_ID`. Nunca guardar un client secret porque este flujo no lo usa.

## 7. systemd

Si el unit ya existe, compararlo y guardar su versión anterior antes de sustituirlo.

```bash
sudo cp /opt/autonogrow/deploy/autonogrow.service.example /etc/systemd/system/autonogrow.service
sudo systemctl daemon-reload
sudo systemctl enable --now autonogrow
sudo systemctl status autonogrow --no-pager
sudo journalctl -u autonogrow -n 100 --no-pager
```

Confirmar que los logs no contienen cookies, credentials Google, booking tokens o datos personales completos.

## 8. Caddy y firewall

Instalar Caddy desde su repositorio oficial para la distribución. Después:

Si `/etc/caddy/Caddyfile` ya contiene otros sitios, no sobrescribirlo: integrar el bloque de AutonoGrow y conservar una copia validada del fichero anterior.

```bash
sudo cp /opt/autonogrow/deploy/Caddyfile.example /etc/caddy/Caddyfile
sudoedit /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Sustituir `app.example.com`. Caddy obtiene TLS y redirige HTTP automáticamente para hostnames públicos válidos.

En el firewall permitir solo SSH administrativo, 80 y 443. La sintaxis depende del proveedor; comprobar las reglas antes de activarlas para no perder SSH. Nunca abrir 8000 públicamente.

Comprobar:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -I https://app.example.com/health
```

La respuesta JSON debe ser exactamente equivalente a `{"status":"ok","app":"autonogrow"}`.

## 9. Pruebas de aplicación

Desde un navegador limpio y herramientas de desarrollo:

1. Abrir landing, owner, admin y customer mediante HTTPS.
2. Iniciar sesión con un owner real y una cuenta business asignada.
3. Confirmar cookie `autonogrow_session`: Secure, HttpOnly, SameSite=Lax, Path=/.
4. Confirmar que una mutación sin `X-CSRF-Token` devuelve 403 y con token funciona.
5. Enviar preflight desde un origen ajeno: no debe recibir `Access-Control-Allow-Origin` válido.
6. Crear una reserva anónima y otra autenticada.
7. Confirmar que `/uploads/businesses/...` sirve logo/galería.
8. Confirmar que el path antiguo `/uploads/{business}/{booking}/{file}` devuelve 404 y el endpoint privado exige sesión/token.
9. Confirmar que el puerto 8000 no responde desde otra máquina.

## 10. Backup y restauración de prueba

```bash
sudo -u autonogrow /opt/autonogrow/.venv/bin/python /opt/autonogrow/scripts/backup_sqlite_uploads.py --output-dir /var/backups/autonogrow --keep 14
sudo -u autonogrow ls -l /var/backups/autonogrow
```

El listado revela nombres/tamaños, no secretos. Copiar un juego a almacenamiento externo cifrado.

Para probar restauración, usar un directorio aislado; no sobrescribir la DB activa:

```bash
sudo install -d -o autonogrow -g autonogrow -m 0750 /var/lib/autonogrow/restore-test
sudo -u autonogrow cp /var/backups/autonogrow/autonogrow_TIMESTAMP.sqlite3 /var/lib/autonogrow/restore-test/autonogrow.db
sudo -u autonogrow sqlite3 /var/lib/autonogrow/restore-test/autonogrow.db 'PRAGMA integrity_check;'
sudo -u autonogrow unzip -t /var/backups/autonogrow/uploads_TIMESTAMP.zip
```

Sustituir `TIMESTAMP` por un juego real. Borrar el directorio de prueba solo después de verificar la ruta exacta y conservar el backup original.

## 11. Logs y operación

- Revisar `journalctl -u autonogrow` y logs de Caddy.
- Configurar límites de journald y alertas de disco, 5xx, certificado y backup.
- Programar el backup diario descrito en `docs/vps_security_deploy_plan.md`.
- Ejecutar una restauración mensual y registrar el resultado.

## 12. Rollback manual

Antes de cada despliegue conservar código anterior identificable, `backend.env` cifrado/protegido y un backup consistente de DB/uploads.

Si el nuevo código falla:

1. Detener solo la aplicación: `sudo systemctl stop autonogrow`.
2. Restaurar la versión de código anterior en `/opt/autonogrow` mediante el mecanismo de releases utilizado.
3. Restaurar el entorno anterior únicamente si sus variables cambiaron.
4. No restaurar la DB automáticamente: las migraciones actuales son aditivas. Restaurarla implica pérdida de datos posteriores y requiere aprobación explícita y un backup previo.
5. Arrancar y comprobar: `sudo systemctl start autonogrow`, `/health`, login y logs.
6. Si el proxy causó el fallo, restaurar su fichero anterior, validarlo y recargarlo.

No usar `rm -rf`, sobrescrituras de DB ni reglas de firewall improvisadas durante el incidente.

## 13. Staging validation

Antes de tocar producción, completar `docs/staging_deploy_checklist.md` en un VPS y dominio separados:

1. Ejecutar localmente `python scripts/predeploy_check.py`; no subir con ningún FAIL.
2. Crear el entorno real de staging a partir de `deploy/staging.backend.env.example`, fuera del repositorio y sin placeholders.
3. Desplegar código, frontend, systemd y proxy siguiendo este runbook, usando exclusivamente rutas y datos de staging.
4. Ejecutar desde una máquina externa:

   ```bash
   python scripts/smoke_test_staging.py --base-url https://staging.example.com
   ```

   Sustituir el dominio. El smoke test no inicia sesión ni imprime cookies/tokens; comprueba health, ruta pública, rechazo anónimo, uploads y headers.

5. Probar manualmente login real owner, business admin y customer. Confirmar permisos entre negocios/cuentas.
6. Revisar cookies en el navegador y probar CSRF con y sin header.
7. Crear una reserva anónima y otra autenticada; confirmar datos, mensajes y auditoría esperados.
8. Subir media pública y un adjunto privado. Comprobar que el primero carga públicamente y el segundo exige sesión o booking token.
9. Ejecutar el backup de staging, copiarlo cifrado fuera del VPS y restaurarlo en una ruta aislada.
10. Revisar journald y proxy: errores, 403/429 anómalos y ausencia de secretos/PII innecesaria.
11. Documentar incidencias, WARN, cambios manuales y tiempos de rollback. Resolverlos o aceptarlos explícitamente antes de programar producción.

Un smoke test con 0 FAIL no sustituye login, CSRF autenticado, IDOR, backup/restore ni revisión de logs, que requieren validación manual.
