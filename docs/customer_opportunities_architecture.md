# Customer Opportunities / Growth Engine V1

## Propósito y alcance

Sprint 7 detecta, persiste, actualiza, resuelve y expira oportunidades comerciales explicables. No genera ni envía mensajes, no aplica descuentos y no utiliza IA o modelos predictivos. La unidad operativa es `CustomerOpportunity`, siempre ligada a un negocio y a un cliente.

Las futuras señales sin cliente (por ejemplo, capacidad libre de agenda o estacionalidad) deben usar una entidad separada y pequeña, conceptualmente `BusinessGrowthSignal`. No se hace nullable `customer_id` ni se mezcla ahora una señal agregada con el ciclo de vida de un cliente. Sprint 8A añade `OpportunityAction` y `BookingAttribution` como capa operativa separada; una futura señal agregada podrá consumir la misma abstracción sin cambiar este detector.

## Modelo

`customer_opportunities` conserva negocio, cliente, tipo, estado, prioridad, fechas, orígenes relacionales, código/motivo explicable y una clave de deduplicación. No guarda mensajes completos ni blobs de metadata. Los orígenes opcionales son `Booking`, `BusinessService`, `Conversation` y `ScheduledCustomerFollowUp`; todos se validan dentro del negocio en API y el motor solo consulta filas tenant-scoped.

`scheduled_customer_followups` representa una fecha concreta indicada por un profesional. Es distinto de la recurrencia estándar. Su estado es `scheduled`, `cancelled` o `converted`; cuando vence produce una oportunidad `scheduled_followup` idempotente.

Servicios incorpora:

- `follow_up_enabled`;
- `follow_up_interval_days` (> 0 cuando se habilita);
- `follow_up_window_days` (>= 0).

Bookings incorpora el snapshot equivalente. La ventana no nula actúa como marcador de captura: `0` también significa que se capturó explícitamente un servicio sin recurrencia. Los bookings anteriores a la migración conservan `NULL` y pueden capturarse al completarse; una reserva nueva nunca cambia su semántica cuando se edita después el servicio.

## Tipos y reglas deterministas

| Tipo | Señal | Espera V1 | Resolución |
|---|---|---:|---|
| `cancelled_not_rebooked` | booking `cancelled` sin booking activo posterior | 3 días | nueva reserva activa |
| `no_show_not_rebooked` | booking `no_show` sin booking activo posterior | 3 días | nueva reserva activa |
| `lead_not_converted` | conversación abierta, teléfono coincidente con Customer, intent comercial y confianza >= 85 | 48 horas | nueva reserva activa posterior |
| `service_due` | booking completado con snapshot activo, dentro de ventana y sin repetición/futuro del mismo servicio | intervalo menos ventana | repetición completada o reserva activa del servicio |
| `scheduled_followup` | seguimiento manual alcanzó `due_at` | fecha exacta | nueva reserva o cancelación del seguimiento |

Los intents comerciales admitidos son exactamente `booking_intent`, `price_intent` y `service_intent`, reutilizando el clasificador por patrones existente. Una conversación `closed`/`resolved`, sin teléfono asociable, reciente o con confianza menor no genera oportunidad. Una conversación produce como máximo una oportunidad, independientemente de sus mensajes.

La ventana de servicio abre en `fecha_realizada + intervalo - ventana` y, si la ventana es positiva, cierra en `fecha_realizada + intervalo + ventana`. Con ventana cero se mantiene 60 días. Un seguimiento manual activo para el booking o servicio tiene prioridad y evita crear un `service_due` incoherente.

## Ciclo de vida

- `pending`: válida y pendiente de atención.
- `actioned`: una persona indica que actuó; aún puede resolverse automáticamente.
- `dismissed`: terminal por decisión humana.
- `resolved`: terminal porque desapareció la condición.
- `expired`: terminal porque superó su vigencia.

La API permite `pending -> actioned|dismissed` y `actioned -> dismissed`. `resolved` y `expired` solo los establece el motor. Una fila terminal no se reabre: un nuevo evento tendrá una clave distinta.

## Dedupe y concurrencia

La identidad estable es negocio + tipo + origen: booking para cancel/no-show, booking+servicio para recurrencia, conversación para lead y follow-up manual para fecha explícita. `UNIQUE (business_id, dedupe_key)` es el guard final. La inserción usa savepoint y tolera una carrera con el mismo constraint en PostgreSQL y SQLite. Ejecutar el motor o el job varias veces actualiza explicaciones/expiración abiertas, pero no duplica ni revive terminales.

## Ejecución temporal

`GrowthOpportunityService.evaluate_business()` no depende de routers. El mantenimiento existente ejecuta la tarea `growth-opportunities` diariamente para negocios `ready`/`active`; `--task growth-opportunities` permite ejecución acotada. La creación de bookings resuelve oportunidades en la misma transacción y los cambios de estado también evalúan el negocio. No se añade un scheduler de aplicación paralelo.

## API y permisos

Rutas bajo `/api/admin/businesses/{business_slug}`:

- `GET /opportunities` y `GET /opportunities/{id}`;
- `POST /opportunities/{id}/dismiss`;
- `POST /opportunities/{id}/actioned`;
- `PATCH /opportunities/{id}/status`;
- `POST /scheduled-followups`;
- `POST /scheduled-followups/{id}/cancel`.

Owner, `business_admin` y `business_staff` reutilizan `require_business_access` para trabajo operativo. Las rutas de configuración de servicios existentes continúan restringidas a owner/admin. IDs cruzados de customer, booking y service se rechazan; list/detail/mutations siempre incluyen `business_id` en la consulta. Las respuestas solo exponen nombre e IDs necesarios, no teléfonos ni contenido de chat.

## Evolución Growth/RRSS

El contexto relacional, tipo, timestamps, business y `reason_code/reason_text` permiten que una futura capa combine `service_due` con `BusinessGrowthSignal` (capacidad, horarios, estacionalidad configurable). Esa capa podrá sugerir una acción o contenido RRSS sin acoplar publicación, descuentos o mensajes a este detector.

## Extensión Sprint 8A

Las acciones asistidas, aprobación explícita, entrega por conversaciones, atribución conservadora y métricas se documentan en `docs/growth_actions_architecture.md`. El detector no envía por sí mismo: resolver oportunidades y cancelar drafts obsoletos sigue ocurriendo dentro de la transacción de booking/mantenimiento.

## Fuera de alcance

No hay IA, scoring opaco, inferencia de intervalos, campañas, promociones, contenido social, publicación ni envío comercial automático. Sprint 8A mide atribución observable; no afirma causalidad ni usa “revenue recovered”.
