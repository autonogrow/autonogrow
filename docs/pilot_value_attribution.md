# Semántica de valor, baseline y ROI

El reporte de piloto responde qué hizo cada módulo sin convertir correlación en causalidad. Rangos
permitidos: 7 días, 30 días o hasta 366 días custom. Toda consulta está limitada por business y
fecha. `Complete` no es fuente de métricas.

## Clasificación

- **Directamente atribuible:** cadena Growth action → attribution → booking completada → snapshot
  de precio/moneda. Métodos existentes: link firmado, ventana conservadora o atribución manual
  auditada.
- **Influenciado/asistido:** relación plausible sin evidencia directa. V1 la explica, pero no la
  suma a ingresos ni al ROI.
- **Valor operativo:** reservas gestionadas, clientes atendidos, propuestas, piezas y publicaciones.

Essential muestra `managed_booking_value`; nunca lo llama ingreso incremental atribuible. Growth
reutiliza `BookingAttribution` y solo suma snapshots completados con moneda conocida. Social informa
actividad editorial; sin tracking suficiente, reservas e ingresos atribuibles son `null`, no cero.
Un módulo desactivado se muestra `disabled`, no “0 € de rendimiento”.

## Coste y ROI

`module_cost_amount/currency/period` vive en `business_module_access`. Es opcional, mensual y no
hardcodea precios. Para un reporte de 30 días con coste positivo, misma moneda y revenue directo
completo:

```text
estimated_net_return = directly_attributable_revenue - module_cost
roi_percentage = (estimated_net_return / module_cost) * 100
return_per_euro = directly_attributable_revenue / module_cost
```

Coste ausente, cero, moneda distinta, rango no mensual o attribution incompleta producen un estado
`unavailable_*`; no se prorratea ni se inventa ROI. Essential/Social no obtienen ROI monetario hasta
tener revenue directo defendible.

## Baseline

`pilot_baselines` guarda una referencia opcional: reservas mensuales, ticket medio, ocupación,
recurrencia, cancelación y no-show. No es obligatoria y no contiene contabilidad. La comparación se
etiqueta “Variación durante el piloto” con `causal_claim=false`; nunca “AutonoGrow causó X”.

APIs: Admin `GET .../value-summary`; Owner `GET .../pilot-value`, `GET/PUT .../pilot-baseline` y
`GET /api/owner/pilot-value`. Faltan para atribución Social fiable un tracking firmado desde pieza
o provider y eventos provider consistentes. Faltan para tiempo ahorrado una metodología validada;
por eso V1 no monetiza horas estimadas.
