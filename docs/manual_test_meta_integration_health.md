# Prueba manual de salud Meta

Usar staging con credenciales de prueba autorizadas. Predeploy y smoke no deben llamar a Meta.

1. Confirmar `alembic current` = `20260804_10` y una sola head.
2. Arrancar API y worker; comprobar heartbeat idle.
3. Owner abre «Control y onboarding de canales» y verifica que no aparecen tokens, teléfono completo ni respuestas Meta.
4. Pulsar «Comprobar ahora». La API debe responder 202 con job queued sin esperar a Meta.
5. Verificar transiciones del job `queued → processing → completed|retry` y heartbeat `meta_integration`.
6. Para una integración sana, comprobar health `healthy`, contador cero y siguiente ejecución.
7. Simular timeout: health warning, retry con backoff, sin revocar ni cambiar capacidades.
8. Retirar suscripción en un activo de prueba: debe aparecer degraded y un job de reparación. La reparación debe auditarse.
9. Revocar un token de prueba: debe aparecer revoked, entrega efectiva false y botón de reconexión.
10. Completar OAuth/Embedded Signup de reconexión: la integración anterior sigue intacta hasta aprobación Owner. Tras aprobar, entrega y automatización continúan según sus flags previos/controlados, nunca se encienden por el health worker.
11. Crear un attempt caducado con token candidato cifrado; ejecutar cleanup y confirmar token destruido, integración/conversaciones intactas.
12. Probar Owner, business_admin y business_staff; Staff no debe acceder y ningún actor puede enviar integration/provider IDs arbitrarios.

Revisar auditoría: scheduled, started, succeeded/failed, degraded/recovered, expiración, suscripción, reconexión y limpieza. Revisar métricas `autonogrow_meta_*` y que logs no contengan `Authorization`, access tokens ni payloads completos.
