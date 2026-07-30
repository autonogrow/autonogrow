# Webhook inbox

Estados: `pending`, `processing`, `processed`, `retry`, `ignored`, `failed`, `dead_letter`, `cancelled`.

La clave idempotente prioriza `message.mid`, después un identificador de evento y finalmente un SHA-256 de proveedor, tipo, sender, recipient, timestamp y hash canónico del evento. La unicidad se aplica en base de datos y los duplicados se capturan con `IntegrityError` dentro de un savepoint.

El payload se conserva solo para procesar. Nunca se copia a logs, auditorías o incidencias. `WEBHOOK_MAX_PAYLOAD_BYTES` limita la recepción antes de insertar.
