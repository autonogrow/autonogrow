# Prueba manual de salida WhatsApp Cloud API

Use una base y cuenta Meta de prueba. No copie tokens, Authorization, firmas ni payloads con datos
personales a logs o tickets.

## Preparación

1. Aplique Alembic a una base temporal.
2. Cree un negocio activo y una integración interna `whatsapp/whatsapp` cuyo
   `external_account_id` sea el Phone Number ID real de prueba.
3. Cifre el access token con el servicio interno; no lo escriba en SQL plano ni lo introduzca desde
   el frontend.
4. Deje la integración `connected`, habilite el canal comercial y configure webhook, app secret y
   verify token sólo en el entorno local seguro.
5. Arranque API y `python -m app.workers.channel_worker`.

## Flujo integrado

1. Envíe desde el teléfono cliente un texto al número de prueba.
2. Confirme un inbox `whatsapp:message:<wamid>` y su transición a `processed`.
3. Compruebe conversación y mensaje inbound con el negocio resuelto por `phone_number_id`.
4. Active una regla automática aplicable y confirme mensaje outbound `queued`, un único outbox
   `whatsapp:outbound-message:<message_id>` y un único movimiento de crédito.
5. Confirme que el worker persiste `provider_message_id` y que el cliente recibe el texto.
6. Reenvíe el webhook inbound: no debe aparecer otro outbox ni otro crédito.

## Estados

Envíe webhooks firmados `sent`, `delivered` y `read` para el ID devuelto. El mensaje debe avanzar y
no retroceder si después llega un estado antiguo. Pruebe `failed` con código de prueba: sólo deben
persistirse código, tipo y mensaje controlado. Un ID desconocido no crea conversación; un
`phone_number_id` distinto no modifica el outbox.

## Panel y fallback

1. Dentro de ventana, el panel debe mostrar “WhatsApp conectado” y “Envío integrado disponible”.
2. “Enviar desde AutonoGrow” debe responder en cola, no entrega inmediata; confirme el outbox.
3. Simule el último inbound con más de 24 horas: el botón integrado queda deshabilitado y aparece el
   aviso de plantilla requerida. No debe existir outbox ni crédito nuevo.
4. “Abrir en WhatsApp” debe abrir `https://wa.me/...` y mostrar que el envío se completa fuera de
   AutonoGrow. No debe crear mensaje, outbox ni crédito.
5. Quite o desconecte la integración: el fallback asistido permanece si el teléfono es válido.

## Aislamiento y errores

1. Cree dos negocios con Phone Number ID distintos; cada conversación y outbox debe usar sólo su
   integración.
2. Intente acceder a la conversación desde el slug del otro negocio: debe devolver 404.
3. Pruebe timeout/429/503: el outbox debe pasar a `retry` con `next_retry_at`.
4. Pruebe token revocado: debe quedar bloqueado sin cinco intentos y la integración `revoked`.
5. Revise logs y respuestas: no deben contener token, Authorization, IDs técnicos innecesarios ni
   cuerpo crudo de Meta.

Detenga API y worker y elimine únicamente la base temporal creada para esta prueba.
