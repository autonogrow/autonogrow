# Recuperación de colas e incidencias

Owner consulta `/api/owner/system/queue-status`. Los dead letters y bloqueos no se reclaman automáticamente. Owner puede reintentar o cancelar con motivo obligatorio; la acción queda auditada.

Antes de reintentar un outbox bloqueado se debe recuperar la integración. Para diagnosticar se usan IDs internos, estado, intento y código seguro; nunca payload, texto, token, firma, cabeceras o ciphertext.

Rollback de esquema: detener worker, ejecutar `alembic downgrade 20260730_02` y arrancar solo la versión anterior. El downgrade elimina únicamente las tres tablas nuevas.
