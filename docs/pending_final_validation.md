# Validación funcional final pendiente

Estas pruebas proceden del Sprint 1 de integraciones Instagram multiempresa. La implementación y
verificación técnica ya existen, pero ninguna prueba de esta lista se ha ejecutado. Estados válidos:
Pendiente, Correcta, Fallida o Bloqueada. No cambiar un estado sin adjuntar evidencia.

| ID | Sprint origen | Prioridad | Precondiciones | Pasos | Resultado esperado | Evidencias a guardar | Estado | Incidencia | Fecha | Responsable |
|---|---|---|---|---|---|---|---|---|---|---|
| IG-S1-01 | Sprint 1 | P0 | Cuenta cliente real conectada; webhook staging | Enviar DM inbound desde cuenta cliente | Webhook acepta y procesa el mensaje | Payload saneado, request ID, captura Instagram | Pendiente | — | — | Sin asignar |
| IG-S1-02 | Sprint 1 | P0 | IG-S1-01; recipient_id conocido | Comparar recipient_id con integración persistida | Se resuelve el negocio correcto | Consulta saneada de integración y conversación | Pendiente | — | — | Sin asignar |
| IG-S1-03 | Sprint 1 | P0 | Dos negocios existentes | Revisar conversaciones tras IG-S1-01 | No aparece conversación en otro negocio | Consultas por business_id | Pendiente | — | — | Sin asignar |
| IG-S1-04 | Sprint 1 | P0 | IG-S1-01 completada | Revisar incidencias y logs | No se genera `instagram_unmapped_account` | Export saneado de incidencias/logs | Pendiente | — | — | Sin asignar |
| IG-S1-05 | Sprint 1 | P0 | Automatización activa y con crédito | Revisar respuesta al inbound | Se ejecuta la automatización configurada | Mensajes, regla aplicada y ledger | Pendiente | — | — | Sin asignar |
| IG-S1-06 | Sprint 1 | P0 | App oficial Instagram y conversación existente | Enviar mensaje echo desde Instagram oficial | Webhook recibe un echo real | Payload saneado y request ID | Pendiente | — | — | Sin asignar |
| IG-S1-07 | Sprint 1 | P0 | IG-S1-06; sender_id conocido | Comparar sender_id con integración | El negocio se resuelve por sender_id | Consulta saneada y trazas de routing | Pendiente | — | — | Sin asignar |
| IG-S1-08 | Sprint 1 | P0 | IG-S1-06 procesada | Consultar mensaje persistido | Echo queda registrado como outbound | Fila sin contenido sensible y captura panel | Pendiente | — | — | Sin asignar |
| IG-S1-09 | Sprint 1 | P0 | IG-S1-06 procesada | Revisar direction/sender_type y automatización | Echo no se interpreta como cliente | Fila de mensaje y ausencia de respuesta automática | Pendiente | — | — | Sin asignar |
| IG-S1-10 | Sprint 1 | P0 | Dos negocios y conversaciones activas | Enviar echo en negocio A; revisar B | No pausa ni altera conversaciones de B | Estados antes/después por business_id | Pendiente | — | — | Sin asignar |
| IG-S1-11 | Sprint 1 | P0 | Integración connected y conversación | Enviar mensaje desde AutonoGrow | El proveedor acepta el envío real | Captura panel, request ID y respuesta saneada | Pendiente | — | — | Sin asignar |
| IG-S1-12 | Sprint 1 | P0 | IG-S1-11; keyring disponible | Trazar selección de credencial sin imprimirla | Se usa el token cifrado de la integración | integration_id/key_version y log saneado | Pendiente | — | — | Sin asignar |
| IG-S1-13 | Sprint 1 | P0 | IG-S1-11 enviado | Revisar conversación en Instagram | Mensaje entregado a destinatario correcto | Captura Instagram y provider message ID | Pendiente | — | — | Sin asignar |
| IG-S1-14 | Sprint 1 | P0 | IG-S1-13 y echo recibido | Esperar/procesar echo | Echo reconcilia el outbound existente | IDs antes/después y log de reconciliación | Pendiente | — | — | Sin asignar |
| IG-S1-15 | Sprint 1 | P0 | IG-S1-14 | Contar mensajes por provider ID | No existen duplicados | Consulta de unicidad/recuento | Pendiente | — | — | Sin asignar |
| IG-S1-16 | Sprint 1 | P0 | Saldo conocido antes de IG-S1-11 | Comparar wallet antes/después | Se consume un único crédito | Saldos y transacción asociada | Pendiente | — | — | Sin asignar |
| IG-S1-17 | Sprint 1 | P0 | IG-S1-16 | Revisar ledger e idempotency key | Movimiento y saldos son correctos | Fila ledger saneada | Pendiente | — | — | Sin asignar |
| IG-S1-18 | Sprint 1 | P1 | IG-S1-11 exitoso | Consultar integración | `last_success_at` se actualiza | Timestamp antes/después | Pendiente | — | — | Sin asignar |
| IG-S1-19 | Sprint 1 | P0 | IG-S1-11 exitoso | Consultar estado integración | Continúa `connected` | Estado antes/después | Pendiente | — | — | Sin asignar |
| IG-S1-20 | Sprint 1 | P0 | Backup de entorno; integración persistida | Retirar las tres variables Instagram antiguas | Entorno arranca sin variables globales | Diff de nombres, nunca valores | Pendiente | — | — | Sin asignar |
| IG-S1-21 | Sprint 1 | P0 | IG-S1-20 | Reiniciar servicio | Arranque correcto y migraciones en head | Status, health y logs saneados | Pendiente | — | — | Sin asignar |
| IG-S1-22 | Sprint 1 | P0 | IG-S1-21 | Repetir inbound real | Routing y automatización siguen correctos | Evidencias equivalentes a IG-S1-01/02/05 | Pendiente | — | — | Sin asignar |
| IG-S1-23 | Sprint 1 | P0 | IG-S1-21 | Repetir echo real | Echo outbound y aislado | Evidencias equivalentes a IG-S1-06/08/10 | Pendiente | — | — | Sin asignar |
| IG-S1-24 | Sprint 1 | P0 | IG-S1-21 | Repetir envío real | Entrega y crédito correctos | Evidencias equivalentes a IG-S1-11/13/16 | Pendiente | — | — | Sin asignar |
| IG-S1-25 | Sprint 1 | P0 | IG-S1-22 a 24 | Revisar logs/configuración/routing | No existe fallback al slug global | Trazas saneadas y configuración sin variables | Pendiente | — | — | Sin asignar |
| IG-S1-26 | Sprint 1 | P0 | Token de test controlable | Configurar/simular token expirado | Integración detecta expiración | Estado integración y respuesta saneada | Pendiente | — | — | Sin asignar |
| IG-S1-27 | Sprint 1 | P0 | IG-S1-26 | Intentar envío | Envío queda bloqueado | Error UI/API y ausencia de llamada útil | Pendiente | — | — | Sin asignar |
| IG-S1-28 | Sprint 1 | P0 | Saldo conocido; IG-S1-27 | Comparar wallet/ledger | No consume crédito | Saldos y ausencia de transacción | Pendiente | — | — | Sin asignar |
| IG-S1-29 | Sprint 1 | P0 | Mock/control OAuth real seguro | Simular respuesta OAuth 190/revocación | Se clasifica como revocado | Respuesta saneada e incidencia | Pendiente | — | — | Sin asignar |
| IG-S1-30 | Sprint 1 | P0 | Dos integraciones; IG-S1-29 en A | Revisar A y B | Solo A queda afectada | Estados por integration_id | Pendiente | — | — | Sin asignar |
| IG-S1-31 | Sprint 1 | P0 | Integración revocada | Completar reconexión OAuth | Credencial nueva se cifra y verifica | Capturas, key_version y timestamps | Pendiente | — | — | Sin asignar |
| IG-S1-32 | Sprint 1 | P0 | IG-S1-31 | Consultar/verificar integración | Recupera `connected` | Estado y verificación Meta saneada | Pendiente | — | — | Sin asignar |
| IG-S1-33 | Sprint 1 | P1 | Incidencias de A y B abiertas | Completar IG-S1-31 y revisar incidencias | Solo se resuelven incidencias de A | IDs/estados antes y después | Pendiente | — | — | Sin asignar |
| IG-S1-34 | Sprint 1 | P0 | Integración connected | Desconectar desde panel/API | Estado pasa a disconnected | Auditoría y estado | Pendiente | — | — | Sin asignar |
| IG-S1-35 | Sprint 1 | P0 | IG-S1-34 | Intentar envío | Envíos quedan bloqueados | Respuesta y ausencia de llamada Meta | Pendiente | — | — | Sin asignar |
| IG-S1-36 | Sprint 1 | P0 | IG-S1-34; confirmación destructiva | Eliminar credenciales de integración | Credenciales quedan eliminadas | Auditoría y columnas de credencial | Pendiente | — | — | Sin asignar |
| IG-S1-37 | Sprint 1 | P0 | IG-S1-36 | Consultar integración | Ciphertext y key_version desaparecen | Consulta saneada | Pendiente | — | — | Sin asignar |
| IG-S1-38 | Sprint 1 | P0 | Historial previo; IG-S1-36 | Abrir/listar conversaciones antiguas | Historial se conserva íntegro | Recuentos y captura panel | Pendiente | — | — | Sin asignar |
| IG-S1-39 | Sprint 1 | P0 | Dos negocios con cuentas Instagram distintas | Ejecutar inbound, echo y outbound en ambos | Cada cuenta usa su integración | Matriz de IDs y capturas de ambos | Pendiente | — | — | Sin asignar |
| IG-S1-40 | Sprint 1 | P0 | IG-S1-39 | Comparar conversaciones, créditos e incidencias | Aislamiento multiempresa completo | Consultas por business_id y ledger | Pendiente | — | — | Sin asignar |
