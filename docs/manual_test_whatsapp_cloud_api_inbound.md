# Prueba manual de recepción WhatsApp Cloud API

Use exclusivamente credenciales de prueba en variables locales. No copie tokens, firmas ni
payloads con datos personales a tickets o logs. Los ejemplos usan valores ficticios.

## Preparación

1. Cree una base temporal actualizada con Alembic.
2. Cree un negocio activo y una `BusinessChannelIntegration` con `channel=whatsapp`,
   `provider=whatsapp`, `external_account_id=PHONE_TEST`, estado `connected` y token nulo.
3. Configure localmente `WHATSAPP_WEBHOOK_ENABLED=true`, un verify token y `META_APP_SECRET`.
4. Para validar firma real, active `WHATSAPP_REQUIRE_SIGNATURE=true`.
5. Arranque API y worker: `cd backend` y `python -m app.workers.channel_worker` en otra terminal.

## Verificación GET

Solicite:

```text
GET /api/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=VERIFY_TEST&hub.challenge=12345
```

Debe responder `200`, cuerpo de texto exacto `12345`. Repita con token o mode incorrectos y sin
challenge: debe rechazar sin revelar el token. Con el webhook deshabilitado debe responder `503`.

## POST firmado

Envíe un JSON con `object=whatsapp_business_account`, una entrada WABA y un
`change[field=messages]`. Incluya `metadata.phone_number_id=PHONE_TEST`, un contacto y un mensaje
`type=text` con ID único. Calcule `X-Hub-Signature-256=sha256=<HMAC hexadecimal>` sobre los bytes
exactos del cuerpo usando el app secret local.

Debe responder rápidamente con `ok=true` y `accepted=1`. Una firma ausente o incorrecta debe
responder `403`; JSON inválido u objeto distinto, `400`; cuerpo sobre el límite, `413`.

## Persistencia y worker

Compruebe en `webhook_inbox_events`:

- `provider=whatsapp`, `channel=whatsapp`, `event_type=message`;
- `provider_event_id` igual al ID de Meta;
- `idempotency_key=whatsapp:message:<ID>`;
- estado inicial `pending`, hash y tamaño informados;
- ningún secreto o cabecera almacenados.

Reenvíe exactamente el mismo evento: `accepted=0`, `duplicates=1`. Envíe después un lote con ese
ID y otro nuevo: sólo el nuevo debe aceptarse.

Después del worker, la fila debe estar `processed`, con `attempt_count=1`, `business_id` e
`integration_id` de la correspondencia `PHONE_TEST`. Debe existir una sola conversación WhatsApp
para el `wa_id` y un mensaje entrante con el ID externo. La integración puede tener token nulo.

## Ausencia de entrega y otros eventos

Con una regla automática aplicable, confirme que se crea una sugerencia manual, pero no un mensaje
saliente, fila en `channel_outbox_messages` ni consumo de crédito. La API debe exponer
`delivery_supported=false` para la conversación WhatsApp.

Envíe un mensaje `image`: debe persistirse y terminar `ignored`, sin conversación. Envíe estados
`sent`, `delivered`, `read` y `failed`: deben terminar procesados sin conversaciones ni outbox.

## Aislamiento multinegocio

Cree dos negocios con `phone_number_id` distintos y envíe un evento para cada uno. Cada conversación
debe pertenecer sólo al negocio resuelto por su ID. Un ID inexistente, una integración inactiva o
una combinación de otro canal deben acabar como fallo permanente y no crear conversación. La base
debe rechazar asignar el mismo `(provider, external_account_id)` a otro negocio.

Al finalizar, detenga API y worker y elimine únicamente la base temporal de esta prueba.
