# Matriz acumulada de validación final

`Pendiente` no implica aceptación. Las filas bloqueantes deben quedar Correctas con evidencia antes
de producción. Los detalles operativos de IG-S1 están en `pending_final_validation.md`.

| Test ID | Área | Descripción | Entorno | Datos necesarios | Riesgo | Automatizada | Manual | Estado | Evidencia | Bloqueante para producción | Sprint de origen |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AUTH-01 | Autenticación | Login/logout y cookies seguras por rol | Staging | Usuarios owner/admin/customer | Alto | Parcial | Sí | Pendiente | — | Sí | Base |
| AUTHZ-01 | Autorización | IDOR y permisos entre roles | Staging | Usuarios con roles distintos | Crítico | Parcial | Sí | Pendiente | — | Sí | Base |
| MULTI-01 | Multiempresa | Recursos de A nunca aparecen en B | Staging | Dos negocios completos | Crítico | Parcial | Sí | Pendiente | — | Sí | Base |
| BOOK-01 | Reservas | Crear, modificar y cancelar reserva | Staging | Servicio, cliente y profesional | Alto | Sí | Sí | Pendiente | — | Sí | Base |
| AVAIL-01 | Disponibilidad | Slots, excepciones, buffers y zona horaria | Staging | Horarios y fechas límite | Alto | Sí | Sí | Pendiente | — | Sí | Base |
| CONV-01 | Conversaciones | Inbound/outbound, pausa y estado | Staging | Conversación de prueba | Alto | Sí | Sí | Pendiente | — | Sí | Base |
| CREDIT-01 | Créditos | Idempotencia, saldo y ledger | Staging | Wallet con saldo conocido | Crítico | Sí | Sí | Pendiente | — | Sí | Sprint créditos |
| INCIDENT-01 | Incidencias | Apertura, deduplicación y recuperación | Staging | Fallos controlados | Alto | Sí | Sí | Pendiente | — | Sí | Sprint incidencias |
| CRYPTO-01 | Cifrado | Cifrar, descifrar y rotar key version | Aislado | Keyring ficticio versionado | Crítico | Sí | No | Pendiente | — | Sí | Sprint 1 |
| MIG-01 | Migraciones | Vacía y heredada alcanzan única head sin pérdida | CI/Aislado | SQLite sintética | Crítico | Sí | No | Pendiente | — | Sí | Industrialización |
| BACKUP-01 | Backups | Backup íntegro y restore aislado | Staging | DB/uploads y keyring protegida | Crítico | Parcial | Sí | Pendiente | — | Sí | Industrialización |
| OWNER-01 | Frontend owner | Navegación y operaciones críticas owner | Staging | Owner autorizado | Alto | No | Sí | Pendiente | — | Sí | Base |
| ADMIN-01 | Frontend admin | Gestión de negocio sin acceso owner | Staging | Admin de negocio | Alto | No | Sí | Pendiente | — | Sí | Base |
| LAND-01 | Landing pública | Carga, negocio, servicios y reserva | Staging | Negocio publicado | Medio | Parcial | Sí | Pendiente | — | Sí | Base |
| SEC-01 | Seguridad | CSRF, CORS, headers, rate limit y secretos | Staging | Origen externo y requests controladas | Crítico | Parcial | Sí | Pendiente | — | Sí | Hardening |
| PERF-01 | Rendimiento básico | Latencia y locks bajo concurrencia prevista | Staging | Dataset representativo | Alto | Parcial | Sí | Pendiente | — | Sí | Industrialización |
| RECOVERY-01 | Recuperación | Restore, rollback de código y validación | Aislado | Release previa y backup | Crítico | Parcial | Sí | Pendiente | — | Sí | Industrialización |
| IG-S1-01 | Instagram | Inbound real desde cuenta cliente | Staging | Cuenta cliente e integración | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-02 | Instagram | Mapping recipient_id al negocio correcto | Staging | Inbound y dos negocios | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-03 | Multiempresa | Inbound no crea conversación cruzada | Staging | Dos negocios | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-04 | Incidencias | Inbound mapeado no genera unmapped account | Staging | Incidencias consultables | Alto | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-05 | Instagram | Inbound ejecuta automatización | Staging | Regla activa y crédito | Alto | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-06 | Instagram | Echo real desde app oficial | Staging | Cuenta oficial | Alto | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-07 | Instagram | Echo usa sender_id para resolver negocio | Staging | Echo y dos cuentas | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-08 | Conversaciones | Echo se registra outbound | Staging | Echo procesado | Alto | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-09 | Conversaciones | Echo no se interpreta como cliente | Staging | Echo procesado | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-10 | Multiempresa | Echo no altera otro negocio | Staging | Dos conversaciones | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-11 | Instagram | Envío real desde AutonoGrow | Staging | Integración connected | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-12 | Cifrado | Envío usa token cifrado de integración | Staging | Keyring real protegida | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-13 | Instagram | Entrega real en Instagram | Staging | Destinatario controlado | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-14 | Instagram | Reconciliación del echo | Staging | Outbound y echo | Alto | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-15 | Conversaciones | Ausencia de mensajes duplicados | Staging | Provider message ID | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-16 | Créditos | Consumo de un único crédito | Staging | Saldo inicial | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-17 | Créditos | Movimiento correcto en ledger | Staging | Ledger accesible | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-18 | Instagram | Actualización de last_success_at | Staging | Integración consultable | Medio | No | Sí | Pendiente | — | No | Sprint 1 |
| IG-S1-19 | Instagram | Integración sigue connected | Staging | Envío exitoso | Alto | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-20 | Instagram | Retirar tres variables globales antiguas | Staging | Backup y env editable | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-21 | Recuperación | Reiniciar sin variables antiguas | Staging | IG-S1-20 | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-22 | Instagram | Repetir inbound sin variables antiguas | Staging | Servicio reiniciado | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-23 | Instagram | Repetir echo sin variables antiguas | Staging | Servicio reiniciado | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-24 | Instagram | Repetir outbound sin variables antiguas | Staging | Servicio reiniciado | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-25 | Multiempresa | No existe fallback al slug global | Staging | Variables retiradas | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-26 | Instagram | Simular token expirado | Staging | Token controlado | Alto | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-27 | Instagram | Token expirado bloquea envío | Staging | IG-S1-26 | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-28 | Créditos | Fallo de token no consume crédito | Staging | Saldo conocido | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-29 | Instagram | Simular revocación/OAuth 190 | Staging | Respuesta controlada | Alto | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-30 | Multiempresa | Revocación afecta solo su integración | Staging | Dos integraciones | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-31 | Instagram | Reconectar integración | Staging | Integración revocada | Alto | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-32 | Instagram | Reconexión recupera connected | Staging | IG-S1-31 | Alto | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-33 | Incidencias | Reconexión resuelve solo sus incidencias | Staging | Incidencias de A/B | Alto | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-34 | Instagram | Desconectar integración | Staging | Integración connected | Alto | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-35 | Instagram | Desconexión bloquea envíos | Staging | IG-S1-34 | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-36 | Cifrado | Eliminar credenciales | Staging | Confirmación explícita | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-37 | Cifrado | Ciphertext desaparece | Staging | IG-S1-36 | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-38 | Conversaciones | Historial sobrevive desconexión | Staging | Conversaciones históricas | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-39 | Multiempresa | Dos negocios y cuentas distintas | Staging | Dos cuentas reales | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
| IG-S1-40 | Multiempresa | Aislamiento completo de cuentas, datos y créditos | Staging | Resultado IG-S1-39 | Crítico | No | Sí | Pendiente | — | Sí | Sprint 1 |
