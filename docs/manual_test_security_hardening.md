# Prueba manual: security hardening

## Preparación local

En `backend/.env`, usar un `SESSION_SECRET` de al menos 32 caracteres, el Google client id real y el owner de prueba. Para probar CSRF y rate limit localmente, activar temporalmente:

```env
APP_ENV=local
COOKIE_SECURE=false
FRONTEND_ORIGINS=http://127.0.0.1:5500,http://localhost:5500
CSRF_ENABLED=true
RATE_LIMIT_ENABLED=true
SECURITY_HEADERS_ENABLED=true
```

Arrancar:

```powershell
cd C:\Dev_Mihai\autonogrow\backend
..\.venv\Scripts\python.exe -m compileall app
..\.venv\Scripts\python.exe -m app.seed
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload

cd C:\Dev_Mihai\autonogrow
python -m http.server 5500
```

## Configuración y CORS

1. Confirmar que local arranca y landing/login/paneles cargan desde `127.0.0.1:5500` y `localhost:5500`.
2. Enviar un preflight con `Origin: https://no-permitido.example`; no debe aparecer `Access-Control-Allow-Origin` para ese origen.
3. Crear una configuración temporal con `APP_ENV=production` y probar por separado: cookie insegura, secreto corto/placeholder, client id vacío, owner vacío, origins vacío/wildcard, CSRF/rate limit/headers desactivados. Cada caso debe impedir importar/arrancar la aplicación con un error explícito.

## Cookie y CSRF

1. Iniciar sesión y revisar Application > Cookies: `autonogrow_session` es HttpOnly, SameSite=Lax, Path=/ y dura 7 días. En local no es Secure; en producción debe serlo.
2. `GET /api/auth/csrf` devuelve token y crea `autonogrow_csrf` no HttpOnly cuando CSRF está activo.
3. Con sesión, ejecutar un POST/PATCH/DELETE protegido sin `X-CSRF-Token`: debe devolver 403.
4. Repetir con el mismo valor de cookie en `X-CSRF-Token`: debe funcionar.
5. Comprobar que GET funciona sin header.
6. Crear una reserva anónima sin cookie de sesión: no debe exigir CSRF. Repetir estando autenticado desde la landing: el wrapper debe adjuntarlo.
7. Cerrar sesión: ambas cookies desaparecen y `/api/auth/me` vuelve a 401.

## Rate limiting y headers

1. Superar 30 requests/minuto en `/api/auth/*`, 12 creaciones/minuto en reservas o 180 requests/minuto en un scope protegido. Debe responder 429 e incluir `Retry-After`.
2. Verificar en una respuesta: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` y `Cross-Origin-Opener-Policy`.
3. En producción HTTPS verificar también `Strict-Transport-Security`.

## Autorización e IDOR

1. Asignar un `business_admin` solo al negocio A. Debe acceder a A y recibir 403 en settings, servicios, reservas, horarios y media del negocio B.
2. Probar ids reales del negocio B en rutas del negocio A: deben responder 404/403, nunca devolver o modificar el recurso.
3. Con dos customers, cada uno debe ver únicamente citas enlazadas a su id/email verificado.
4. En upload de una reserva anónima probar: sin token (401), token ajeno (403), token correcto (201/200). Un admin de otro negocio no debe obtener acceso.

## Uploads, logs y auditoría

1. Subir un `.exe`, un MIME falso, una imagen cuya firma no coincide y un fichero mayor que `UPLOAD_MAX_SIZE_MB`: todos deben rechazarse.
2. Subir/eliminar logo o galería y comprobar que su URL pública `/uploads/businesses/...` funciona.
3. Subir un adjunto válido. La respuesta debe usar `/api/businesses/.../attachments/{id}/content`, nunca una URL estática privada.
4. Probar el contenido privado: sin sesión/token devuelve 401, token ajeno 403, token correcto o admin/customer propietario 200.
5. Probar la antigua URL `/uploads/{business_slug}/{booking_id}/{filename}`: debe devolver 404.
6. Revisar salida del backend: no debe mostrar credenciales Google, cookies, headers completos, emails/teléfonos completos, mensajes o booking tokens.
7. Consultar SQLite: `audit_logs` debe contener `login_success`, `logout`, cambios de negocio/usuario, estados de cita, settings y media. IP y user-agent deben aparecer solo como hashes.
8. Revisar `metadata_json` y confirmar que no contiene `credential`, cookies, `booking_manage_token`, teléfono o mensaje WhatsApp.
9. Forzar un 403 y confirmar `failed_access_403` sin ruta ni datos personales completos.

## Backup

1. Ejecutar desde el repo: `.venv\Scripts\python.exe scripts\backup_sqlite_uploads.py --output-dir backups-test --keep 2`.
2. Confirmar que crea un `.sqlite3` consistente y un ZIP con `uploads/`, pero sin `.env`.
3. Ejecutarlo tres veces y comprobar que conserva dos juegos.
4. Restaurar el SQLite en una ruta aislada, abrirlo y comprobar tablas/recuentos. Extraer el ZIP aparte y revisar una muestra de media pública y adjuntos privados.
5. Eliminar `backups-test` al terminar; no subir backups al repositorio.

## Regresión funcional

Validar login Google, owner, admin, landing, reserva anónima/autenticada y customer portal. Crear/editar negocio y servicio, cambiar horarios, confirmar/reagendar/rechazar/completar cita y comprobar mensajes/reseñas.
