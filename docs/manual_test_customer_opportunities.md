# Pruebas manuales: Customer Opportunities

## Preparación

1. Aplicar `alembic upgrade head` y confirmar una sola head `20260814_14`.
2. Ejecutar `python scripts/run_maintenance.py --task growth-opportunities --apply --json` cuando un escenario requiera alcanzar una fecha sin un evento nuevo.
3. Entrar como owner/admin en el negocio indicado. Revisar **Configuración > Servicios** y **Crecimiento > Oportunidades**.
4. Confirmar en cada tarjeta que se ve el cliente, tipo, motivo y fecha, pero no contenido completo de conversaciones ni envío automático.

## Peluquería / manicura

1. En `demo-manicura`, activar seguimiento de Manicura semipermanente a 21 días, ventana 4.
2. Completar una reserva y verificar en base de datos que el booking guarda snapshot 21/4.
3. Mover la fecha completada en datos de prueba a hace 18 días y ejecutar el motor: debe aparecer `service_due`.
4. Cambiar ahora el servicio a 28 días. Repetir el motor: la oportunidad y booking anteriores siguen explicando 21 días.
5. Desactivar seguimiento para otro servicio: no debe producir oportunidad.

## Taller

1. En `demo-taller`, configurar Cambio de aceite a 180 días y ventana 14.
2. Completar una cita con fecha de hace 166 días y ejecutar el motor.
3. Debe aparecer `service_due` con Cambio de aceite, intervalo 180, fecha realizada y comienzo de ventana. No debe inferir recomendaciones mecánicas adicionales.

## Cancelación y no-show

1. Cancelar una reserva identificada y establecer el evento a hace más de 3 días en datos de prueba.
2. Ejecutar dos veces el motor: debe existir un solo `cancelled_not_rebooked`.
3. Repetir con estado existente `no_show`: debe crear un solo `no_show_not_rebooked`.
4. Descartar una tarjeta y volver a ejecutar: no reaparece.

## Lead

1. Crear Customer y conversación con el mismo teléfono.
2. Enviar una consulta que el clasificador existente marque `booking_intent`, `price_intent` o `service_intent` con confianza >= 85.
3. Ajustar `last_inbound_at` a hace más de 48 horas y ejecutar el motor: aparece un `lead_not_converted`.
4. Añadir mensajes a la misma conversación y repetir: no hay spam ni duplicados.
5. Verificar que intent no comercial, conversación cerrada o teléfono sin Customer no generan oportunidad.

## Seguimiento manual

1. Crear con `POST /api/admin/businesses/{slug}/scheduled-followups` una fecha futura asociada a customer y, opcionalmente, booking/service.
2. Antes de la fecha no hay oportunidad. Tras alcanzar la fecha y ejecutar el motor aparece `scheduled_followup`.
3. Repetir el mismo POST: devuelve el seguimiento existente (`created=false`).
4. Cancelar con `POST /scheduled-followups/{id}/cancel`: el seguimiento queda `cancelled` y una oportunidad abierta queda descartada.

## Rebooking

1. Desde una oportunidad pendiente de cancelación, lead, no-show o seguimiento manual, crear una reserva activa del cliente.
2. Debe quedar `resolved` en la misma transacción.
3. Para `service_due`, reservar el mismo servicio: se resuelve. Reservar otro servicio no resuelve esa recurrencia.

## Multi-business y roles

1. Crear datos equivalentes en negocios A y B.
2. Como admin/staff de A, listar, leer, descartar y gestionar oportunidades de A.
3. Intentar IDs de oportunidad/customer/booking/service de B en rutas de A: respuesta 404/400, sin revelar datos.
4. Verificar que staff puede operar oportunidades, pero no cambiar recurrencia del servicio; admin/owner sí puede.
