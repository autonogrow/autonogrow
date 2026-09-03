# Ciclo V1 de solicitudes de reseña por Customer

## Contrato

Cada pareja `business_id + customer_id` puede tener un único ciclo canónico de
solicitud de reseña. La Booking que lo creó se conserva como origen y las
Bookings posteriores del mismo Customer reutilizan ese ciclo sin cambiar su
origen.

La identidad procede exclusivamente del `Customer` relacionado con la Booking.
No se fusionan personas por nombre, teléfono o email. En el esquema actual
`Booking.customer_id` es obligatorio; si una fila corrupta careciera de Customer
estable, la operación falla cerrada y no intenta inferir identidad.

## Persistencia y datos legacy

`ReviewRequest` incorpora `customer_id` y `is_customer_cycle_anchor`. Un índice
único parcial sobre `(business_id, customer_id)` se aplica solamente a filas
ancla. Esto permite conservar solicitudes históricas que ya estaban duplicadas
por Customer sin relajar la garantía para escrituras futuras.

La migración enlaza cada solicitud existente con el Customer de su Booking. Por
cada pareja Business+Customer, la solicitud más antigua queda como ancla; las
posteriores permanecen visibles como historia legacy con el indicador de ancla
desactivado. No se borra ni se reescribe el estado de ninguna solicitud.

Se elige un índice parcial en vez de `UNIQUE(business_id, customer_id)` porque el
segundo impediría migrar negocios con ciclos históricos múltiples. La marca de
ancla es infraestructura de compatibilidad, no un segundo ciclo operativo.

## Lifecycle

Las transiciones admitidas son:

- `pending -> copied | sent | skipped`
- `copied -> sent | skipped`
- una escritura idempotente al mismo estado

`sent` y `skipped` son terminales. El backend rechaza reaperturas implícitas como
`sent -> copied` o `skipped -> sent`.

Un fallo pertenece a `MessageOutbox`, no a `ReviewRequest`. Un mensaje `failed`
puede volver a abrirse usando la misma fila y la Booking de origen; nunca crea
otro ciclo ni otro mensaje. Marcar una solicitud como enviada u omitida sincroniza
su outbox relacionado dentro de la misma transacción.

## Concurrencia y frontend

La finalización de Bookings ya serializa las mutaciones por Business. El POST
manual aplica el mismo bloqueo. El índice parcial es la garantía final y las
inserciones capturan un conflicto concurrente para recuperar la fila ganadora en
vez de devolver un error 500.

El frontend agrupa la elegibilidad por `customer_id`, muestra como máximo la
Booking completada más reciente de un Customer sin ciclo y conserva el historial
por Booking de origen. Las métricas cuentan solicitudes persistidas, no nuevas
visitas ni reseñas publicadas.

`BusinessReview` sigue separado: no demuestra qué Customer publicó una reseña y
no interviene en esta deduplicación.
