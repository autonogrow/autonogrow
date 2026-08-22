# Runbook de soporte de pilotos

## Severidad y respuesta

- P0: seguridad, posible pérdida de datos o todos sin servicio. Activar mantenimiento si protege
  datos, conservar evidencia, parar acciones mutantes, escalar de inmediato.
- P1: un piloto no puede reservar u operar una función crítica contratada. Responder y diagnosticar
  durante la ventana acordada; aplicar rollback/forward-fix controlado.
- P2: módulo secundario degradado con core operativo. Comunicar workaround y plan.
- P3: cosmético o mejora UX. Registrar sin interrumpir operación.

Registrar cada caso con `pilot_issue_template.md`, sin tokens ni PII innecesaria. Consultar build,
business, rol, módulos y readiness antes de concluir que una integración está caída.

| Síntoma | Comprobaciones | Acción segura | Escalado |
|---|---|---|---|
| Cliente no puede reservar | business activo, servicio, horario, slots y `booking_ready` | corregir configuración; probar guest booking | P1 si booking listo sigue fallando |
| Admin no ve cita | business/rol, filtros, rango y booking ID tenant-scoped | limpiar filtros y recargar; consultar endpoint con sesión autorizada | P1 si datos existen y UI/API divergen |
| Instagram desconectado | Social activo, integration/health, token expiry | pedir reconexión; mantener publisher apagado | P2; P1 solo si Social es crítico acordado |
| WhatsApp | teléfono y modo integrado/asistido | usar assisted `wa.me`; Cloud no bloquea piloto | P2 si no hay fallback válido |
| Google login cliente | configuración, cuenta/link y error seguro | reservar como invitado; revisar link conservador | P2; guest roto es P1 |
| Archivo no carga | límite/MIME, referencia DB y storage reconciliation dry-run | reintentar fichero válido; no borrar referencia | P1 si evidencia del piloto peligra |
| Job atascado | queue status, claim/attempts, heartbeat, módulo activo | retry/cancel Owner existente con motivo; no editar DB | P1/P2 según impacto |
| Health degradado / 5xx | `/health`, `/ready`, build, DB/head, disco, logs con request ID | mantenimiento si hay riesgo; rollback compatible o forward-fix | P0/P1 |
| Módulo activo no usable | entitlement, activation, integration, service flag y worker por separado | corregir el estado incorrecto; sanity script | P1 para función contratada |
| Capability incorrecta | Owner audit y filas por business | PATCH Owner explícito; conservar datos | seguridad/tenant mismatch es P0 |
| Restauración | backup DB+uploads+release+keyring y restore test | restaurar primero aislado; validar antes de tráfico | P0/P1 con aprobación |

Mantenimiento y storage son dry-run por defecto; véanse [maintenance](maintenance_operations.md),
[queue recovery](queue_incident_recovery.md), [backup verification](backup_verification.md) y
[restore](postgresql_backup_restore.md). No ejecutar cleanup destructivo como diagnóstico.
