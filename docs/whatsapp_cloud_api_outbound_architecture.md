# Envío mediante WhatsApp Cloud API

## Sender oficial

`send_whatsapp_text_message` implementa el contrato `ProviderSendResult` y realiza:

```text
POST https://graph.facebook.com/{META_GRAPH_API_VERSION}/{phone_number_id}/messages
```

El cuerpo contiene `messaging_product=whatsapp`, destinatario individual, tipo `text`,
`preview_url=false` y un máximo de 4096 caracteres. `phone_number_id` y `wa_id` se validan como
identificadores numéricos antes de construir la URL. Una respuesta sólo es éxito si contiene
`messages[0].id`.

No se usa SDK de WhatsApp Web ni automatización de navegador. Authorization, token, texto completo,
respuesta cruda y datos personales no se registran.

## Integración y aislamiento

La integración se resuelve internamente por `business_id`, `channel=whatsapp` y
`provider=whatsapp`. `external_account_id` contiene el `phone_number_id`; `metadata_json` puede
conservar WABA ID. El token permanece en `encrypted_access_token`, protegido por AES-256-GCM y una
versión de clave. Debe estar `connected` o `degraded`, no expirada y tener cifrado completo.

El frontend no proporciona provider, integration ID, phone number ID, token ni business ID. La
creación de outbox vuelve a comprobar negocio, conversación, canal, proveedor e integración. La
restricción única `(provider, external_account_id)` evita asignar un número a dos negocios.

## Disponibilidad y dos caminos

Las respuestas de conversación separan:

- `delivery_supported`: existe sender en el sistema;
- `provider_configured`: existe una integración persistida para el negocio;
- `integrated_delivery_available`: además, canal comercial habilitado y ventana abierta;
- `assisted_delivery_available`: existe un teléfono válido para construir `wa.me`.

Una integración persistida puede tener `provider_configured=true` y, aun así, no estar disponible
para enviar si está desconectada, el token falta o no se puede descifrar, el `phone_number_id` es
inválido, el canal comercial está deshabilitado o la ventana está cerrada.

“Enviar desde AutonoGrow” crea un mensaje `queued` y outbox. “Abrir en WhatsApp” pide al backend un
enlace oficial, devuelve `sent=false` y no crea mensaje, outbox ni crédito. El enlace no se considera
evidencia de entrega.

## Ventana de atención

El texto libre sólo se permite dentro de `WHATSAPP_CUSTOMER_SERVICE_WINDOW_HOURS`, con rango seguro
de 1 a 24 y valor 24. La referencia es el último `ConversationMessage` inbound WhatsApp con ID Meta
y timestamp de proveedor válido. El cálculo se hace en UTC. Timestamp ausente, inválido o futuro
cierra la ventana de forma conservadora; un outbound nunca la renueva.

Fuera de ventana no se crea outbox ni se intenta una plantilla. Automatización y panel reciben
`whatsapp_template_required` y conservan la sugerencia para intervención humana.

## Outbox, worker e idempotencia

La creación usa `whatsapp:outbound-message:{conversation_message_id}` y la unicidad de
`conversation_message_id`. El worker reclama la fila común, valida contexto y credenciales,
descifra el token y llama al sender sin transacción abierta. Sólo después de una respuesta Meta
válida persiste `provider_message_id` y marca el mensaje `sent`.

Timeout, conexión, 429, 500, 502, 503, 504 y errores temporales Meta reintentan con el backoff común.
Token revocado, permisos, destinatario, payload, ventana, cuenta suspendida o número no registrado
son permanentes o bloqueantes. Un timeout aislado no cambia el estado de integración.

## Estados

Los webhooks `sent`, `delivered`, `read` y `failed` se buscan por `provider_message_id` y vuelven a
validar provider, canal, integración, negocio y `phone_number_id`. El mensaje avanza de forma
monotónica; `read` no retrocede. El outbox conserva `sent` para estados exitosos y pasa a `failed`
cuando corresponde. Código y tipo seguros se guardan en campos existentes; el mensaje crudo de Meta
se descarta. IDs desconocidos se procesan sin crear conversaciones.

Sin migración, `ConversationMessage.delivery_status` y `raw_payload_json.whatsapp_delivery`
conservan el estado agregado y el timestamp Meta más reciente; `ChannelOutboxMessage.sent_at` y
`failed_at` conservan los hitos locales de envío y fallo. El resto del JSON histórico del mensaje se
mantiene al fusionar estos metadatos. Este sprint no conserva timestamps individuales separados para
cada transición `sent`, `delivered` y `read`: un estado posterior sustituye el agregado anterior.

## Automatización y créditos

Una regla automática sólo envía con feature, periodo, canal, regla, confianza, ausencia de pausa,
crédito, integración y ventana válidos. Se bloquea la conversación en PostgreSQL y se comprueba si
ese inbound ya produjo un outbound. El crédito se consume una vez por `related_message_id` después
de crear una entrega válida encolada.

No hay consumo por sugerencia, fallback, integración ausente, plan deshabilitado o ventana cerrada.
Los reintentos del mismo outbox no consumen de nuevo. Si Meta falla permanentemente después de
encolar, se mantiene la política comercial existente: no hay devolución automática inventada.

## Límites

Sólo se envía texto libre dentro de ventana. Quedan fuera templates reales, multimedia, campañas,
Embedded Signup, OAuth visual, BSP externo y mensajes proactivos. El siguiente sprint debe abordar
plantillas aprobadas y alta guiada sin debilitar estas validaciones.
