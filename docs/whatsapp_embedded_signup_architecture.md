# WhatsApp Embedded Signup (Sprint 4C)

## Alcance y contrato oficial

Contrato verificado el 3 de agosto de 2026 en la documentación oficial de Meta para
Embedded Signup y Tech Providers:

- SDK: `https://connect.facebook.net/en_US/sdk.js`.
- Inicialización: `FB.init({ appId, autoLogAppEvents: true, xfbml: true, version })`.
- Login: `FB.login(callback, { config_id, response_type: "code",
  override_default_response_type: true, extras: { setup: {} } })`.
- El código se obtiene de `response.authResponse.code`.
- Evento del SDK: `WA_EMBEDDED_SIGNUP`; el flujo estándar termina con `FINISH` y aporta
  `data.business_id`, `data.waba_id` y `data.phone_number_id`.
- Intercambio server-side: `GET /{version}/oauth/access_token` con `client_id`,
  `client_secret` y `code`. El resultado es un Business Integration System User Access
  Token, llamado también business token.
- Suscripción: `POST /{WABA-ID}/subscribed_apps`.
- La versión configurada para este sprint es explícita (`v26.0` en los ejemplos) y no
  cambia la versión del sender existente.

Solo se soporta el final estándar `FINISH`. Variantes como `FINISH_ONLY_WABA` y el
onboarding de WhatsApp Business App quedan pendientes de diseño y pruebas externas. El
registro `/{phone-number-id}/register` requiere un PIN de seis dígitos: este sprint no lo
solicita, transmite ni almacena. Si Meta no deja el número operativo, la candidatura queda
bloqueada con `registration_required`.

Fuentes oficiales:

- <https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation/>
- <https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider/>
- <https://www.postman.com/meta/whatsapp-business-platform/documentation/du6gzjv/embedded-signup>

## Flujo y límites de confianza

1. Un Owner concede el canal y define quién puede conectarlo.
2. El administrador autorizado inicia un intento de diez minutos. El backend devuelve
   únicamente App ID, Configuration ID, versión Graph, URL del SDK, parámetros públicos y
   un nonce opaco.
3. La base de datos conserva solo SHA-256 del nonce y una huella HMAC de la sesión. Un
   intento nuevo invalida el anterior equivalente.
4. El navegador acepta mensajes HTTPS de `facebook.com` o sus subdominios y envía el
   evento y el código al backend como indicios, nunca como prueba de propiedad.
5. Una comparación atómica consume `pending → processing`. Desde ese instante no existe
   reintento ni replay: cualquier cancelación o fallo exige iniciar otro intento.
6. El adaptador de Meta intercambia el código, inspecciona token/App ID/scopes/granular
   scopes, verifica Meta Business → WABA → phone number, estado y nombre, y suscribe la app.
7. El token se cifra antes de formar una candidatura `candidate_ready`. No se crea ni
   reemplaza todavía una integración utilizable.
8. El Owner puede reintentar verificación/suscripción, rechazar o aprobar. La aprobación
   exige suscripción y registro confirmados, vuelve a comprobar colisiones entre negocios y
   promueve el candidato dentro de la transacción.

Al promover se guarda `external_account_id = phone_number_id` y
`provider_account_id = WABA ID`. La integración anterior se mantiene intacta hasta ese
momento. Un reemplazo cierra el routing antiguo sin reasignar conversaciones históricas.
El control queda aprobado con `integrated_delivery_enabled=false` y
`automation_enabled=false`.

## Seguridad y operación

- Los POST están cubiertos por la protección CSRF existente y por límites específicos de
  inicio/finalización.
- No se persisten state en claro, authorization code, token en claro, PIN, cookies,
  respuestas Meta completas ni payload crudo del SDK.
- API, auditoría y UI Owner no exponen WABA ID, phone number ID, número completo ni token.
- Las colisiones de WABA o phone number entre negocios devuelven un error genérico y se
  verifican de nuevo bajo bloqueo al aprobar.
- Suspender o revocar un canal invalida intentos y candidaturas activas.
- La simulación WhatsApp se deshabilita fuera de tests cuando Embedded Signup está activo.
- Renovación/expiración automática del business token, configuración comercial de Meta,
  pagos, credit line y homologación como Tech Provider pertenecen a Sprint 4D u operación
  externa.
