# Prueba manual del ciclo de automatización de 30 días

Ejecutar primero en staging y usando un owner de pruebas. Todas las fechas de API deben
estar en UTC (`Z`); el navegador puede mostrarlas en la zona horaria local.

1. Crear un negocio sin periodo y abrir su bloque **Plan, automatización y cuota**.
   Esperado: `pending_renewal`, sin inicio, vencimiento ni pago confirmado.
2. Pulsar **Confirmar pago y renovar 30 días** e introducir un motivo o referencia.
   Esperado: confirmación con negocio, plan, límite, consumo y fechas previstas.
3. Confirmar el pago.
   Esperado: `period_started_at` coincide con la confirmación y `period_ends_at` es
   exactamente 30 días posterior; estado `active`.
4. Verificar que `auto_used_current_period` pasa a cero y que plan, límite y canales no
   cambian.
5. Provocar una automatización entregada correctamente.
   Esperado: el consumo aumenta exactamente en una unidad.
6. En staging, ajustar `period_ends_at` a un instante pasado mediante **Corrección
   administrativa del periodo**, indicando un motivo y confirmando que no es un pago.
7. Consultar de nuevo el panel o enviar un mensaje entrante.
   Esperado: transición a `pending_renewal`; fechas y consumo anteriores se conservan.
8. Enviar un mensaje entrante que normalmente produciría una respuesta automática.
   Esperado: el entrante se guarda, no se llama al proveedor, no se crea un fallo técnico,
   no cambia el consumo y la causa segura es `period_pending_renewal`.
9. Enviar una respuesta manual desde el panel.
   Esperado: continúa funcionando si el canal y las reglas operativas lo permiten.
10. Confirmar un nuevo pago después del vencimiento.
    Esperado: el nuevo periodo comienza ahora, no en el vencimiento anterior, dura 30
    días y el consumo vuelve a cero.
11. Intentar renovar otra vez mientras el periodo sigue activo.
    Esperado: aparece la advertencia de días restantes y se requiere confirmación expresa.
12. Repetir inmediatamente la misma petición con el mismo `Idempotency-Key`.
    Esperado: respuesta idempotente, sin nuevas fechas ni auditorías duplicadas.
13. Suspender comercialmente el negocio y confirmar otro pago.
    Esperado: las nuevas fechas se registran, pero `period_status` continúa `suspended`
    hasta que el owner reactive la función por separado.
14. Revisar auditoría y ambos paneles.
    Esperado: acciones de pago/renovación/expiración/corrección, panel owner con todos los
    controles y panel admin exclusivamente de lectura para cuota y periodo.
