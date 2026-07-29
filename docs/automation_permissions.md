# Permisos de automatización y ciclo comercial de 30 días

## Regla comercial

La cuota de automatización utiliza ciclos móviles de **30 días exactos**. No es un mes
natural ni se renueva al cambiar de mes. El ciclo comienza en el instante UTC en que un
owner confirma manualmente el pago y termina con `period_started_at + timedelta(days=30)`.

La confirmación de pago:

- fija `payment_confirmed_at` y `period_started_at` al instante de confirmación;
- fija `period_ends_at` exactamente 30 días después;
- reinicia `auto_used_current_period` a cero;
- conserva plan, límite, canales y comportamiento al alcanzar la cuota;
- activa el periodo si no existe una suspensión comercial manual;
- no elimina una suspensión manual del owner.

No existe renovación, prórroga ni reinicio automático. Al alcanzar el vencimiento, la
evaluación perezosa cambia una sola vez `active` a `pending_renewal`, conserva fechas y
consumo y bloquea únicamente nuevos mensajes automáticos. Los entrantes, mensajes
manuales y paneles continúan según sus reglas habituales. El vencimiento comercial no
es una incidencia técnica.

## Estados y precedencia

- `active`: existe un periodo no vencido y la función comercial está habilitada.
- `pending_renewal`: no existe un periodo confirmado vigente. Requiere pago manual.
- `suspended`: el owner ha suspendido comercialmente la función. Tiene precedencia
  sobre un pago o vencimiento; confirmar un pago no levanta esta suspensión.

El estado operativo `automation_enabled`, los canales habilitados y el límite no
duplican `period_status`. Para un envío automático se comprueba, en orden: función
comercial, periodo activo/no vencido, canal, activación operativa, pausa de conversación,
cuota y proveedor.

## Renovación anticipada y tardía

Una renovación anticipada sustituye el periodo vigente y comienza en el momento de la
confirmación; los días restantes no se acumulan. Requiere `confirm_active_period=true`
y el panel muestra una advertencia con los días restantes.

Una renovación tardía también empieza en el instante del nuevo pago, nunca en el
vencimiento anterior. No se descuentan días retroactivamente. `Idempotency-Key` y una
protección contra repeticiones inmediatas evitan crear dos periodos o dos auditorías por
doble clic. Periodo, contador y auditoría se confirman en una única transacción.

## Matriz de permisos

| Acción | Owner | Business admin | Business staff | Cliente |
|---|---:|---:|---:|---:|
| Ver periodo y vencimiento | Sí | Sí, de su negocio | No | No |
| Confirmar pago | Sí | No | No | No |
| Iniciar o renovar periodo | Sí | No | No | No |
| Corregir fechas | Sí, con motivo | No | No | No |
| Reiniciar consumo por pago | Sí | No | No | No |
| Consultar consumo y límite | Sí | Sí, de su negocio | No | No |
| Ver créditos incluidos y adicionales | Sí | Sí, de su negocio | No | No |
| Comprar créditos adicionales | Sí | No | No | No |
| Ajustar saldos de créditos | Sí, con motivo | No | No | No |
| Ver libro de movimientos | Sí | No | No | No |
| Ajustar consumo administrativamente | Sí, con motivo | No | No | No |
| Suspender/reactivar comercialmente | Sí | No | No | No |
| Pausar/reactivar operativamente | Sí | Sí, con periodo y función activos | No | No |
| Cambiar plan, límite o canales | Sí | No | No | No |
| Editar reglas y plantillas autorizadas | Sí | Sí, de su negocio | No | No |

La autorización se aplica en FastAPI y vuelve a comprobarse dentro de los endpoints
sensibles. Los contratos Pydantic usan `extra="forbid"`; fechas, estado, pago o consumo
inyectados en una petición de business admin reciben HTTP 422.

## Endpoints owner y auditoría

- `GET/PATCH /api/owner/businesses/{business_id}/automation-settings`
- `POST /api/owner/businesses/{business_id}/automation-period-renewal`
- `POST /api/owner/businesses/{business_id}/automation-period-adjustment`
- `POST /api/owner/businesses/{business_id}/automation-usage-adjustment`

La renovación exige `reason`; `amount`, `payment_method` y `external_reference` son
opcionales y solo sirven como metadatos de conciliación. La corrección administrativa
exige motivo, fechas con zona horaria y `confirm_no_payment=true`; no cambia
`payment_confirmed_at` ni reinicia el consumo.

Acciones: `automation_payment_confirmed`, `automation_period_renewed`,
`automation_period_expired` y `automation_period_adjusted`, además de los cambios de
plan, límite, consumo, canales y suspensión. La auditoría registra owner, negocio,
fechas anteriores/nuevas, consumo anterior/nuevo, plan, límite, motivo, metadatos
opcionales, request ID y timestamp. Nunca guarda credenciales, datos bancarios
completos, tarjetas, secretos ni conversaciones.

## Datos, UTC y compatibilidad

La fuente de verdad es:

- `period_started_at` (`datetime`, nullable);
- `period_ends_at` (`datetime`, nullable);
- `payment_confirmed_at` (`datetime`, nullable);
- `period_status` (`active`, `pending_renewal` o `suspended`).

Se almacena y transmite UTC; la API devuelve ISO 8601 con `Z` y el navegador presenta
las fechas en la zona local. El campo `period_yyyymm` se conserva temporalmente como
deprecated para compatibilidad, pero no calcula fechas ni reinicia consumo.

La migración ligera añade los cuatro campos de forma idempotente. Una migración única
concede a los registros existentes un periodo de 30 días desde el instante de migración,
sin modificar consumo, plan, límite, canales o suspensión y dejando
`payment_confirmed_at=null` para no inventar un pago histórico. Los negocios creados
después nacen en `pending_renewal` hasta su primera confirmación manual.

## Despliegue y comprobación manual

Realizar una copia de seguridad de la base de datos antes del despliegue. Después,
instalar el código, reiniciar el backend para ejecutar la migración idempotente y validar
OpenAPI/healthcheck primero en staging.

Prueba manual recomendada: crear un negocio sin periodo, confirmar un pago, verificar
30 días exactos y consumo cero, simular consumo y vencimiento, comprobar
`pending_renewal` sin envío automático, verificar que entrantes/manuales continúan,
confirmar otro pago desde la fecha actual y revisar auditoría y ambos paneles.
El procedimiento reproducible completo está en `docs/manual_test_automation_periods.md`.
