# Pruebas manuales: autenticación, permisos y portal cliente

## Configuración local

1. En Google Cloud crea un cliente OAuth 2.0 de tipo **Aplicación web**.
2. Añade como orígenes JavaScript autorizados:
   - `http://127.0.0.1:5500`
   - `http://localhost:5500`
3. Copia `backend/.env.example` a `backend/.env` y configura:
   - `GOOGLE_CLIENT_ID`: id del cliente web, terminado normalmente en `.apps.googleusercontent.com`.
   - `SESSION_SECRET`: secreto aleatorio largo, distinto en producción.
   - `OWNER_ALLOWED_EMAILS`: emails owner separados por comas.
   - `APP_ENV=local`.
   - `COOKIE_SECURE=false` en HTTP local; usar `true` bajo HTTPS.
4. Instala `backend/requirements.txt`, ejecuta la seed e inicia backend y servidor estático.
5. No configures client secret de Google: este flujo recibe un ID token de Google Identity Services y lo verifica en backend.

## A. Sesión

1. `GET /api/config/public` devuelve solo `google_client_id` y `app_env`.
2. `GET /api/auth/me` sin cookie devuelve `401`.
3. Inicia sesión con Google y comprueba `GET /api/auth/me`.
4. En las herramientas del navegador confirma la cookie `autonogrow_session`: HttpOnly, SameSite=Lax y duración de siete días.
5. Confirma que credential, ID token y access tokens no aparecen en localStorage ni sessionStorage.
6. `POST /api/auth/logout` elimina la cookie y el siguiente `/api/auth/me` devuelve `401`.
7. Sin `GOOGLE_CLIENT_ID` o `SESSION_SECRET`, el login debe mostrar un error de configuración claro.

## B. Owner

1. `GET /api/owner/businesses` sin login devuelve `401`.
2. Un email incluido en `OWNER_ALLOWED_EMAILS` accede al Owner Panel y obtiene `200`.
3. Un usuario autenticado no owner obtiene `403`.
4. Añade un email en “Usuarios del negocio”; debe aparecer como pendiente hasta su primer login Google.
5. Inicia sesión con ese email y comprueba que se vincula sin crear otro usuario.
6. Cambia el rol, desactiva y reactiva la asignación.

## C. Admin por negocio

1. Abre el admin sin cookie: debe aparecer “Acceso del negocio” y las APIs devuelven `401`.
2. Un usuario asignado carga su negocio completo.
3. El mismo usuario abre otro slug no asignado y recibe `403` / “Tu cuenta no tiene acceso a este negocio”.
4. Owner puede abrir cualquier admin.
5. Expira o borra la cookie con el admin abierto: la siguiente acción debe volver al login.
6. Comprueba Resumen, Crecimiento, Reservas, Mensajes, Servicios, Horarios, Datos, Reseñas y Marca.

## D. Media y uploads

1. `POST /api/admin/businesses/{slug}/media/logo` sin login devuelve `401`.
2. Usuario asignado u owner puede subir JPG, PNG o WEBP válidos.
3. Usuario de otro negocio obtiene `403`.
4. SVG, MIME/extensión no admitidos, firma de archivo falsa y exceso de tamaño devuelven `400`.
5. La galería pública sigue cargando desde `/uploads`.
6. Tras crear una reserva pública con fotos, el frontend usa `booking_manage_token`; repetir el upload sin cookie ni cabecera `X-Booking-Token` devuelve `401`.

## E. Cliente final

1. `GET /api/customer/bookings` sin login devuelve `401`.
2. Abre `autonogrow-customer/index.html`, entra con Google y comprueba perfil, próximas citas e historial.
3. Edita teléfono y nombre preferido.
4. Desde la landing, inicia sesión y crea una reserva: la respuesta indica `linked_to_account=true` y aparece en “Mis citas”.
5. La tarjeta muestra negocio, servicio, fecha, estado, dirección, landing y WhatsApp cuando procede.

## F. Landing pública

1. Sin login cargan negocio, servicios, disponibilidad, calendario y galería.
2. Crea una reserva anónima: funciona y devuelve `linked_to_account=false`.
3. La reserva autenticada queda vinculada; la anónima mantiene `customer_user_id=null`.
4. “Entrar” es opcional y “Mis citas” abre el portal.
5. No se guarda el token Google en el navegador.

## G. Regresión y códigos

1. Sin sesión, owner/admin/customer privados responden `401`.
2. Con sesión sin permisos responden `403`.
3. ID token inválido o email no verificado responde `400`.
4. Ejecuta reservas, WhatsApp directo, reseñas, branding, servicios, horarios y crecimiento.
5. Ejecuta la seed dos veces y confirma que usuarios, asignaciones, reservas, branding y uploads no se machacan.

## Deuda técnica posterior

- Gestión de consentimiento y política de privacidad para producción.
- Protección CSRF explícita si se habilitan integraciones cross-site o cookies `SameSite=None`.
- Revocación centralizada de sesiones y listado de dispositivos.
- 2FA, recuperación de cuenta y permisos más finos para `business_staff`.
- Gestión de cancelación/reagendado por cliente usando el token público.
- HTTPS, dominio real, cookies Secure y cabeceras de seguridad en despliegue.
