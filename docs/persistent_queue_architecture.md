# Arquitectura de colas persistentes

El POST de Instagram valida tamaño, firma y JSON, separa cada evento y lo inserta en `webhook_inbox_events`. Tras el commit responde 200. No resuelve negocios, ejecuta automatizaciones, consume créditos ni llama a Meta.

`python -m app.workers.channel_worker` es un proceso independiente. Reclama inbox en transacciones cortas, procesa conversación y automatización en una transacción, y crea `ConversationMessage`, `channel_outbox_messages` y el movimiento idempotente de crédito juntos. Después reclama outbox, carga y descifra la integración, cierra la transacción, llama a Meta y persiste el resultado en una sesión nueva.

Los locks caducan y pueden recuperarse. Un único worker atiende ambas colas en SQLite. No se arranca ningún worker desde FastAPI.

## Crédito

La disponibilidad se valida antes de responder. El consumo ocurre al crear correctamente el mensaje y su outbox y usa `related_message_id` como clave única. Los reintentos no crean mensaje, outbox ni consumo adicionales. Si la integración está bloqueada antes de encolar, no se consume. Un dead letter conserva el consumo y la trazabilidad; no hay devolución automática.
