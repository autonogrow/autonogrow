# Instagram Login — arquitectura Sprint 4B

Contrato revisado el 3 de agosto de 2026 contra la documentación oficial de Meta para
[Instagram API with Instagram Login](https://www.postman.com/meta/instagram/folder/6raa77c/instagram-api-with-instagram-login),
[permisos de Instagram Login](https://www.postman.com/meta/workspace/instagram/documentation/23987686-9386f468-7714-490f-9bfc-9442db5c8f00) y
[suscripción de webhooks](https://www.postman.com/meta/instagram/request/23987686-0223707a-7035-46a2-8015-1fdf7249278f).
La versión validada por código y tests es `v23.0`, configurable mediante
`INSTAGRAM_LOGIN_GRAPH_API_VERSION`; no modifica `META_GRAPH_API_VERSION` de otras rutas.

Sprint 4D comprueba periódicamente perfil profesional, cuenta, expiración conocida y `messages` en `subscribed_apps`. Puede reparar únicamente esa suscripción idempotente. OAuth y permisos nuevos siempre requieren interacción y nueva aprobación Owner.
Antes de desplegar debe confirmarse que esa versión está habilitada en el panel Meta.

## Flujo y autoridad

```text
Owner permite Instagram
  → Admin inicia OAuth con CSRF
  → state opaco de un solo uso
  → Instagram Login
  → callback ligado a la misma sesión
  → code intercambiado solo en backend
  → token largo + identidad Business/Creator + permisos mínimos
  → suscripción del campo messages
  → candidatura cifrada candidate_ready / control pending_approval
  → Owner aprueba
  → BusinessChannelIntegration connected
  → envío y automatización continúan apagados
```

Para una conexión inicial no se crea ninguna integración definitiva antes de la
aprobación. La candidatura vive temporalmente en `instagram_oauth_attempts`. En una
reconexión o sustitución la integración activa no se modifica durante OAuth.

## Configuración

```dotenv
INSTAGRAM_LOGIN_ENABLED=false
INSTAGRAM_LOGIN_CLIENT_ID=
INSTAGRAM_LOGIN_CLIENT_SECRET=
INSTAGRAM_LOGIN_REDIRECT_URI=https://app.autonogrow.tld/api/integrations/instagram/callback
INSTAGRAM_LOGIN_GRAPH_API_VERSION=v23.0
INSTAGRAM_OAUTH_ATTEMPT_TTL_SECONDS=600
INSTAGRAM_CANDIDATE_REVIEW_TTL_HOURS=72
INSTAGRAM_SIMULATED_ONBOARDING_TEST_ONLY=false
```

En staging/producción, habilitar Login exige proveedor Instagram, firma de webhook,
keyring AES-256-GCM, URI HTTPS exacta y un origen incluido en `FRONTEND_ORIGINS`. Client
ID y client secret pertenecen al producto Instagram Login; no se duplican ni se asumen
idénticos a las credenciales Meta históricas.

## State, sesión y redirección

El backend genera 48 bytes aleatorios codificados URL-safe. Solo entrega el valor opaco a
Meta; almacena SHA-256, una huella HMAC de la cookie de sesión, negocio, usuario, control,
propósito, retorno interno y expiración. El inicio es POST autenticado y CSRF. El callback
usa una transición compare-and-swap `pending → processing`; `consumed_at` marca el instante
exacto desde el que el state no puede reutilizarse. Un fallo posterior queda `failed` y
requiere iniciar otro OAuth.

Las únicas rutas de retorno se generan en servidor:

- `/autonogrow-admin/index.html?b=<slug-resuelto>`;
- `/autonogrow-owner/index.html`.

No se acepta una URL de retorno, `business_id` ni cuenta desde el callback.

## Intercambio, permisos e identidad

El cliente tipado usa timeouts y categorías de error fijas. Nunca registra respuestas
crudas. El code se intercambia en `api.instagram.com`; el token inicial se cambia por uno
de larga duración en `graph.instagram.com`. El code y el token corto solo existen en
memoria.

Scopes centralizados:

- `instagram_business_basic`;
- `instagram_business_manage_messages`.

El intercambio debe devolver ambos. Faltantes producen `permissions_incomplete`; permisos
inesperados se descartan y no se persisten como concedidos. `/me` debe identificar una
cuenta `BUSINESS` o `CREATOR`. El ID de routing `user_id` se guarda como
`external_account_id`; el ID scoped se conserva solo como metadato controlado.

## Cifrado, webhook y errores

El token largo se cifra con el servicio AES-256-GCM existente antes de escribirlo. La
cuenta se suscribe únicamente a `messages` mediante `subscribed_apps`; el webhook global y
la verificación `X-Hub-Signature-256` no cambian.

Si la autorización es válida pero la suscripción falla, la candidatura permanece
`candidate_ready`, con diagnóstico seguro. El Owner puede reintentar. La aprobación se
bloquea hasta obtener `subscribed`. Cancelación, expiración, rechazo y revocación limpian
la credencial candidata.

## Aprobación, reconexión y sustitución

La promoción Owner es transaccional. Una cuenta ya vinculada o pendiente para otro negocio
se rechaza sin revelar cuál. La misma cuenta actualiza la única integración. Una cuenta
distinta queda como `replacement` y la anterior continúa operativa hasta aprobar.

Al promover una sustitución se cierran las conversaciones Instagram anteriores y se
retiran sus identificadores de routing, conservando mensajes e historial. Así un ID de
remitente de la cuenta nueva no puede reutilizar un hilo de la cuenta anterior.

Una aprobación inicial fija el control en `approved`, pero deja
`integrated_delivery_enabled=false` y `automation_enabled=false`. En un reemplazo se
conservan las capacidades que ya estaban autorizadas; OAuth nunca las enciende.

## Límites y siguiente sprint

- No hay renovación automática de tokens; corresponde a Sprint 4D.
- App Review/Advanced Access y configuración global del webhook se validan en Meta.
- La limpieza por expiración se ejecuta al iniciar o revisar intentos; una tarea periódica
  puede añadirse en Sprint 4D.
- Sprint 4C ampliará el onboarding oficial de otros canales sin reutilizar credenciales.
