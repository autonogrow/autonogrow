# Prueba manual: Centro de Conversaciones v1

Para envío integrado y asistido de WhatsApp, ventana de atención y estados de Cloud API, siga
también `docs/manual_test_whatsapp_cloud_api_outbound.md`. “Abrir en WhatsApp” no debe
contabilizarse como mensaje enviado.

## Preparación

- Arrancar el backend para que SQLAlchemy cree de forma aditiva `conversations`,
  `conversation_messages` y `conversation_templates`.
- En local, si `WEBHOOK_TEST_SECRET` está vacío, el webhook simulado se puede usar sin
  cabecera. Fuera de local la variable y la cabecera son obligatorias.
- No usar secretos reales en comandos, documentación ni capturas.

## Crear una conversación manual

1. Entrar en Admin y abrir **Conversaciones**.
2. Como owner o `business_admin`, pulsar **Crear conversación de prueba**.
3. Elegir canal, indicar nombre, teléfono o usuario y añadir un mensaje inicial.
4. Confirmar que aparece como pendiente y que el mensaje se muestra como entrante.

`business_staff` puede consultar y responder, pero no ve el creador manual ni la gestión
de plantillas.

## Simular un mensaje entrante

Ejemplo para staging, sustituyendo dominio, slug y secreto de prueba por los valores del
entorno autorizado:

```bash
curl -X POST https://staging.autonogrow.es/api/webhooks/test/inbound-message \
  -H "Content-Type: application/json" \
  -H "X-Autonogrow-Webhook-Secret: test-secret" \
  -d '{
    "business_slug": "estudio-prueba",
    "channel": "instagram",
    "external_user_id": "ig-user-123",
    "customer_name": "Cliente Instagram",
    "customer_username": "cliente_demo",
    "body": "Hola, quería una cita"
  }'
```

Enviar un segundo mensaje con el mismo negocio, canal y `external_user_id`. Debe reutilizar
la conversación y dejarla en estado pendiente.

## Responder y usar respuestas rápidas

1. Seleccionar una conversación.
2. Pulsar **Enlace de reserva**, **Servicios**, **Ubicación** o **Bienvenida**.
3. Comprobar que el texto renderizado rellena el cuadro y que se pueden hacer cambios.
4. Pulsar **Enviar**. En v1 solo se registra un mensaje outbound con estado `sent`; no se
   llama a Instagram ni WhatsApp.
5. Confirmar que la conversación pasa a respondida.

Variables disponibles en plantillas:

- `{business_name}`
- `{business_slug}`
- `{public_booking_url}`
- `{business_phone}`
- `{business_address}`

## Estados y filtros

1. Usar **Marcar pendiente**, **Marcar cerrada** y **Reabrir**.
2. Filtrar por pendiente/respondida/cerrada y por canal.
3. Buscar por nombre, teléfono, usuario y contenido del último mensaje.
4. En un negocio sin datos debe aparecer “Todavía no hay conversaciones.”

## Permisos y aislamiento

1. Owner: abrir cualquier negocio y gestionar conversaciones y plantillas.
2. `business_admin`: gestionar únicamente su negocio.
3. `business_staff`: listar, leer, responder y cambiar estado; no gestionar plantillas.
4. Customer y usuario no autenticado: deben recibir `403` y `401`, respectivamente.
5. Intentar consultar desde un negocio A el id de una conversación de B: debe devolver `404`.

## Integración Instagram

Instagram API v1 dispone de webhook firmado, inbound real y outbound de texto opcional. Consulta `docs/manual_test_instagram_v1.md` para configuración y limitaciones.

## Pendiente para una integración multi-negocio

La estructura admite `channel=instagram`, `external_user_id`, `customer_username`,
`provider_message_id` y `raw_payload_json`. Para una integración completa por negocio siguen pendientes:

- cuenta profesional de Instagram;
- página de Facebook vinculada;
- app en Meta Developers;
- permisos de Instagram Messaging y revisión de la app;
- OAuth y asociación independiente entre negocios y cuentas;
- renovación segura de tokens;
- actualización real de estados de entrega y lectura.

No se han añadido credenciales reales al repositorio. El provider permanece desactivado por defecto.
