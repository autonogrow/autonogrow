# Certificación manual posterior al deploy

Ejecutar en orden. No marcar staging como certificado antes de completar los 17 pasos. Ante un
fallo, devolver siempre: número de paso, hora UTC, SHA, comando/acción, status y request/job ID o
extracto redactado. Nunca devolver cookies, DSN, tokens, firmas ni URLs firmadas completas.

1. **Desplegar el commit 10A.** Instalar la release mediante el mecanismo versionado del VPS en
   `/opt/autonogrow` y comprobar `git rev-parse HEAD`. Esperado: SHA exacto del commit 10A y árbol
   limpio. Si falla: devolver SHA observado y `git status --short`.
2. **Aplicar dependencias.** Ejecutar `/opt/autonogrow/backend/.venv-next/bin/python -m pip install -r
   backend/requirements.txt` y después `/opt/autonogrow/backend/.venv-next/bin/python -m pip check`.
   Esperado: instalación y `pip check` con exit 0. Si falla: devolver paquete/conflicto y últimas
   líneas sin URLs privadas.
3. **Verificar Alembic.** Ejecutar con `/opt/autonogrow/backend/.venv-next/bin/python` los comandos
   `-m alembic current`, `-m alembic heads` y, con backup confirmado,
   `scripts/manage_migrations.py upgrade` seguido de `... validate`. Esperado: una head y current
   `20260814_19`. Si falla: devolver revisiones current/head y recomendación del script.
4. **Publicar frontend.** Tras convertir una sola vez el directorio legacy al symlink documentado,
   ejecutar `sudo RELEASE_ID=<SHA> SOURCE_ROOT=/opt/autonogrow scripts/publish_frontend.sh`.
   Esperado: symlink `/var/www/autonogrow` a una release completa con el SHA. Si falla: devolver
   destino del symlink y el archivo requerido indicado por el script.
5. **Validar Caddy.** Integrar la plantilla sin pisar otros sites y ejecutar `sudo caddy validate
   --config /etc/caddy/Caddyfile`; solo entonces `sudo systemctl reload caddy`. Esperado: config
   válida y reload sin error. Si falla: devolver versión de Caddy y error de validación redactado.
6. **Reiniciar backend.** Ejecutar `sudo systemctl restart autonogrow.service` y comprobar
   `curl --fail https://staging.autonogrow.es/ready`. Esperado: `{"status":"ready"}`. Si falla:
   devolver `systemctl show -p ActiveState,NRestarts` y request ID si existe.
7. **Reiniciar workers.** Reiniciar `autonogrow-worker.service` y, tras revisar los flags de
   publishing, iniciar `autonogrow-instagram-publisher.service`. Su `ExecStartPre` ejecuta
   `/opt/autonogrow/backend/.venv-next/bin/python -m app.workers.instagram_publish_worker --check`
   con el usuario y environment de la unidad. Esperado: ambas unidades activas y JSON `ok=true`,
   `worker_enabled=false` mientras el flag siga desactivado y ningún job reclamado. Si falla:
   devolver unidad, ActiveState/NRestarts y salida segura del check en journald.
8. **Comprobar servicios.** Ejecutar `systemctl is-active/is-enabled` para backend, ambos workers y
   `autonogrow-maintenance.timer`; consultar `systemctl list-timers`. Esperado: active/enabled, sin
   restart loop y un único scheduler de mantenimiento a las 04:30 más hasta 10 minutos de jitter.
   Si falla: devolver unidad y propiedades.
9. **Ejecutar certificación.** Desde el VPS y desde una máquina externa ejecutar
   `/opt/autonogrow/backend/.venv-next/bin/python scripts/certify_staging.py --base-url https://staging.autonogrow.es
   --expected-git-commit <SHA> --local-system --json-output /tmp/staging-certification.json`
   (`--local-system` solo en VPS). Esperado: cero `FAIL/BLOCKER`. Si falla: devolver el JSON seguro.
10. **Revisar HTTPS/HSTS.** En navegador privado inspeccionar certificado, redirect HTTP y response
    headers. Esperado: cadena/hostname válidos, TLS moderno, sin bucle y HSTS exacto
    `max-age=31536000` (sin preload/includeSubDomains). Si falla: devolver URL final, status, issuer y
    valor del header, nunca cookies.
11. **Validar páginas legales.** Abrir `/privacy/` y `/data-deletion/` sin sesión. Esperado: 200,
    HTTPS y contenido/enlaces correctos. Si falla: devolver path, status y captura sin datos personales.
12. **Comprobar Meta Integration Health.** En Owner/Admin abrir la cuenta profesional controlada.
    Esperado: healthy, publishing available, scope presente y token cifrado/presente. Si falla:
    devolver solo estados y códigos seguros, nunca token ni account secret.
13. **Ejecutar publication preflight.** Crear/aprobar un JPEG de prueba y ejecutar
    `/opt/autonogrow/backend/.venv-next/bin/python scripts/instagram_publication_preflight.py
    --business-id <ID> --content-id <ID> --json`.
    Esperado: `ok`, `publishing_available`, `version_approved`, `format_supported` y
    `signed_url_ready` verdaderos, modo `meta`, hostname staging. Si falla: devolver JSON e IDs.
14. **Realizar primera publicación JPEG.** Caption: `Publicación técnica de validación AutonoGrow —
    staging.`; pulsar Publicar ahora una sola vez con cuenta controlada. Esperado: un único job y
    transición sin reenvío manual. Si falla: devolver content/version/job ID y código seguro.
15. **Verificar el post en Instagram.** Abrir la cuenta controlada y comprobar imagen/caption.
    Esperado: exactamente un post identificable como staging. Si falla: devolver captura, hora y
    media ID si existe; no repetir Publish hasta revisar estado.
16. **Confirmar `published` en AutonoGrow.** Refrescar contenido, historial y provider state.
    Esperado: `published`, media ID persistido, un solo resultado e historial/auditoría coherentes.
    Si falla: devolver estados, IDs, intentos y request/job correlation.
17. **Revisar logs.** Revisar la ventana con `journalctl` para tres servicios y el log de Caddy.
    Esperado: sin traceback/5xx anómalos, Authorization/cookies/tokens/queries firmadas ni PII; signed
    media y webhook siguen correlacionables por ruta/request ID. Si falla: devolver unidad/archivo,
    tipo de hallazgo y línea totalmente redactada.
