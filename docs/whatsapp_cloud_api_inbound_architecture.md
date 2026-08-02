# Recepción persistente de WhatsApp Cloud API

## Flujo y autenticidad

`GET /api/webhooks/whatsapp` implementa la verificación de Meta. Sólo acepta
`hub.mode=subscribe`, exige challenge y compara `hub.verify_token` con `WHATSAPP_VERIFY_TOKEN`
mediante comparación constante. El token no se registra ni se devuelve.

`POST /api/webhooks/whatsapp` lee el cuerpo una vez y aplica `WEBHOOK_MAX_PAYLOAD_BYTES`. Cuando
`WHATSAPP_REQUIRE_SIGNATURE=true`, valida `X-Hub-Signature-256` con HMAC SHA-256 y el
`META_APP_SECRET` común. Después valida JSON, `object=whatsapp_business_account` y una lista
`entry`. El endpoint sólo normaliza y persiste; no crea conversaciones ni ejecuta automatización.

`WHATSAPP_WEBHOOK_ENABLED=false` mantiene ambos endpoints inactivos sin exigir credenciales. En
producción, activarlo obliga a configurar un verify token no-placeholder, el app secret y la firma.

## Normalización e idempotencia

Cada `entry` y `change[field=messages]` puede producir eventos independientes:

- `message`: texto entrante con `message_id`, `phone_number_id`, WABA ID, remitente, nombre,
  timestamp y texto;
- `unsupported_message`: mensaje no textual, persistido y posteriormente marcado `ignored` sin
  inventar texto ni descargar contenido;
- `status`: `sent`, `delivered`, `read` o `failed`, almacenado y marcado procesado sin conciliación
  de outbox en este sprint. Otros estados quedan `ignored`.

Cambios sin mensajes ni estados se ignoran sin crear filas. Sólo se persiste el payload normalizado,
no cabeceras ni secretos. Se conservan `payload_hash` y `payload_size_bytes`.

Las claves estables son:

- mensajes: `whatsapp:message:{message_id}`;
- estados: `whatsapp:status:{message_id}:{status}:{timestamp}`;
- sólo cuando falta una identidad de Meta: `whatsapp:derived:{sha256}`.

La restricción única de `webhook_inbox_events.idempotency_key` evita duplicados. Un lote se procesa
evento por evento mediante savepoints, por lo que un duplicado no descarta eventos nuevos.

## Procesamiento, negocio y conversaciones

El worker reclama la fila y `process_channel_inbox_event` selecciona el procesador por el
`provider` persistido. WhatsApp sólo acepta la combinación `provider=whatsapp` y
`channel=whatsapp`.

Para texto, el procesador busca exactamente una `BusinessChannelIntegration` con:

- `provider=whatsapp`;
- `channel=whatsapp`;
- `external_account_id=phone_number_id`;
- `integration_status` igual a `connected` o `degraded`.

El `business_id` procede únicamente de esa fila; no se usa slug global ni negocio por defecto. La
restricción única `(provider, external_account_id)` impide que dos negocios compartan el mismo
`phone_number_id`, y la consulta vuelve a rechazar una correspondencia ambigua. También exige que
el negocio esté activo. La entrada no descifra ni necesita `encrypted_access_token`.

La conversación se crea o reutiliza por negocio, canal WhatsApp y `wa_id` del remitente. El mensaje
se guarda como `direction=inbound`, `sender_type=customer`, conserva el ID de Meta y se deduplica
otra vez dentro del negocio antes de ejecutar el motor común.

Integración inexistente o no utilizable, combinación proveedor/canal errónea y payload estructural
inválido son fallos permanentes con códigos y mensajes seguros. Los errores de base de datos siguen
la clasificación reintentable común. No se registran tokens, firmas, cabeceras ni payloads completos.

## Automatización sin sender

WhatsApp está registrado exclusivamente en `INBOX_PROCESSORS` e `INBOX_CHANNELS_BY_PROVIDER`. No
aparece en `PROVIDER_SENDERS` ni en `DELIVERY_PROVIDERS_BY_CHANNEL`, así que
`delivery_supported(channel="whatsapp")` es falso.

Cuando una regla permitiría responder automáticamente, el motor crea una sugerencia manual con
`reason=delivery_not_supported`. No crea mensaje saliente, no crea outbox, no marca una respuesta
como enviada y no consume crédito. Las reglas almacenadas no se reescriben.

## Límites y prueba local

Este sprint sólo recibe texto. No implementa multimedia, templates, OAuth, Embedded Signup,
mensajes proactivos, sender Cloud API ni conciliación completa de estados. La WABA queda conservada
en el payload normalizado; el `phone_number_id` ocupa `external_account_id`, por lo que no se
requiere migración.

Para probar, use una base temporal, cree una integración directamente en fixtures o servicios
internos y siga `docs/manual_test_whatsapp_cloud_api_inbound.md`. Nunca ponga secretos reales en el
repositorio. El siguiente sprint de entrega deberá implementar el sender real y sólo entonces
registrar WhatsApp como proveedor de salida.
