# Concurrencia de base de datos

El aislamiento global es `READ COMMITTED`. Cada operación crítica mantiene la transacción corta y
no incluye llamadas a Meta, sleeps ni procesamiento largo.

- Inbox/outbox: seleccionar por elegibilidad y `FOR UPDATE SKIP LOCKED`, marcar lock, commit y
  procesar después. SQLite mantiene su estrategia de un worker.
- Créditos: bloquear la wallet, releer idempotencia, consumir incluidos antes que adicionales y
  escribir ledger. Checks impiden balances negativos o inconsistentes.
- Reservas: bloquear la fila del negocio, recalcular disponibilidad, bloquear solapamientos y hacer
  una comprobación final. Serializa mutaciones del mismo negocio, no de negocios distintos.
- Disponibilidad y personal: usan el mismo lock de negocio que las reservas.
- Integraciones: la llamada al proveedor ocurre sin transacción; después se bloquea solo la
  integración que recibirá el nuevo estado/ciphertext.

Deadlock y serialization failure son reintentables solo en el límite de operación, con rollback
completo y backoff acotado. Lock timeout y pool timeout se clasifican aparte. Nunca se reutiliza una
Session tras un error sin rollback.
