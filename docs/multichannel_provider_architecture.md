# Arquitectura persistente de proveedores multicanal

## Flujo de entrada

El webhook valida y divide el payload del proveedor antes de persistir cada evento en
`webhook_inbox_events`. La recepción no ejecuta automatización ni llama a APIs externas. La clave
idempotente del evento y la restricción única de la tabla evitan duplicados.

El worker reclama el evento y llama a `process_channel_inbox_event(db, inbox_event_id)`. Esta
entrada lee el `provider` persistido y selecciona un procesador en `INBOX_PROCESSORS`. Instagram y
WhatsApp están registrados para entrada. Un proveedor desconocido lanza
`UnsupportedChannelProvider`, queda como fallo permanente con un mensaje seguro y nunca se marca
silenciosamente como procesado. La combinación persistida de canal y proveedor también debe
coincidir con `INBOX_CHANNELS_BY_PROVIDER`.

Cada procesador conserva su enrutado por cuenta, crea o reutiliza la conversación y entrega el
mensaje al motor común de automatización. El dispatcher no duplica esas reglas. WhatsApp resuelve
el negocio exclusivamente mediante una integración `whatsapp/whatsapp` cuyo
`external_account_id` coincide con el `phone_number_id` receptor.

## Flujo de salida

El motor de conversaciones deriva el proveedor desde el canal y la configuración interna. Nunca
acepta un proveedor elegido por el frontend. Para un canal con entrega persistente comprueba que la
integración:

- pertenece al mismo negocio;
- coincide en canal y proveedor;
- está `connected` o `degraded`;
- tiene credenciales cifradas completas y no expiradas;
- tiene un destinatario externo.

Después crea el mensaje de conversación y una fila en `channel_outbox_messages`. La creación valida
de nuevo la relación entre negocio, conversación e integración. Es idempotente por
`conversation_message_id` y usa la clave `{provider}:outbound-message:{conversation_message_id}`.
No se modifican filas históricas.

El worker reclama la fila, selecciona el sender mediante `PROVIDER_SENDERS[row.provider]`, descifra
las credenciales sólo después de validar todo el contexto y realiza la llamada sin una transacción
de base de datos abierta. Al finalizar persiste el estado y `provider_message_id`.

## Proveedores soportados

| Proveedor | Inbox persistente | Outbox persistente | Sender real |
| --- | --- | --- | --- |
| Instagram | Sí | Sí | Sí |
| WhatsApp | Sí | Sí | Sí, texto libre dentro de ventana |

`delivery_supported` expresa capacidad del sistema. Para WhatsApp, `provider_configured` expresa
que existe una integración persistida; su operatividad se refleja por separado en
`integration_status` e `integrated_delivery_available`. Este último exige credenciales utilizables,
canal comercial y ventana de atención. `assisted_delivery_available` sólo indica que puede generarse
un enlace oficial `wa.me`; nunca equivale a entrega.

## Entrega WhatsApp

WhatsApp usa `POST /{phone_number_id}/messages` mediante el Graph API oficial. El
`external_account_id` de la integración es el `phone_number_id`; el destinatario es el `wa_id` de
la conversación. El worker descifra el token después de validar el contexto y persiste el ID
devuelto por Meta.

El texto libre sólo se encola durante las 24 horas posteriores al último inbound real con timestamp
Meta válido. Fuera de ventana se crea una sugerencia y se requiere una plantilla, aún fuera de
alcance. El fallback asistido no crea `ConversationMessage`, outbox ni consumo de créditos.

La arquitectura detallada está en `docs/whatsapp_cloud_api_outbound_architecture.md`.

## Errores, seguridad y responsabilidades

Los timeouts, rate limits, errores de conexión y respuestas HTTP transitorias conservan el backoff
y el máximo de intentos. Credenciales inválidas o integraciones no disponibles bloquean el envío.
Payloads inválidos y proveedores no soportados son permanentes. Sólo se guardan códigos y mensajes
seguros; tokens y cuerpos completos del proveedor no se registran ni se devuelven al frontend.

Los webhooks son responsables de autenticidad y persistencia; los procesadores, de traducir eventos
al motor común; el motor, de política conversacional y automatización; el outbox, de idempotencia y
estado de entrega; y los adapters, exclusivamente del protocolo externo del proveedor.

La respuesta serializada de conversación expone `channel`, `provider_configured`,
`integration_status` y `delivery_supported`. `instagram_provider_configured` se mantiene
temporalmente sólo para compatibilidad con el panel Admin actual.
