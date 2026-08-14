# Business Growth Signals — arquitectura V1

## Objetivo y límites

`BusinessGrowthSignal` convierte datos operativos agregados en una explicación reproducible y una recomendación comercial genérica. No usa LLM, ML, predicción, descuentos, contenido, publicación ni envío masivo. Una señal nunca crea `OpportunityAction`: para actuar sobre clientes se abre el listado de `CustomerOpportunity` y se reutiliza el flujo explícito de Sprint 8A.

Cada registro conserva `observed_json`, `baseline_json` y `explanation_json`. Los tres usan objetos JSON pequeños con `schema_version: 1`; no contienen nombres ni listas de clientes. `observed` y `baseline` contienen únicamente cifras y contexto estable. `explanation` contiene `title`, `what_happened`, `comparison`, `why_it_matters` y `suggested_action`.

## Modelo y lifecycle

- `BusinessGrowthSignal`: negocio, tipo, estado, severidad, scope, servicio/evento opcional, periodo, caducidad, explicación, observación, baseline, recomendación y `dedupe_key`.
- `BusinessCalendarEvent`: evento definido por el negocio, periodo, categoría libre, servicio opcional, habilitación y repetición anual simple.
- Estados: `active`, `dismissed`, `resolved`, `expired`.
- Severidad: `info`, `low`, `medium`, `high`; siempre deriva de reglas descritas abajo.
- Scopes V1: `business` y `service`. El contrato deja sitio para scopes futuros sin inventar staff/location.

La unicidad `(business_id, dedupe_key)` es la defensa final ante concurrencia. Ocupación y pools usan bucket ISO semanal; retorno y demanda usan bucket mensual; eventos usan evento/año. Una evaluación actualiza el registro activo de su bucket. Si la condición desaparece, pasa a `resolved`. Un registro descartado/resuelto/caducado no se reactiva dentro del mismo bucket; una ventana posterior sí puede crear otro. Nunca se borra el historial.

## Reglas y thresholds centralizados

Las constantes viven en `business_growth_signal_service.py`.

### `low_future_occupancy`

- Ventana: mañana y los 7 días completos siguientes.
- Capacidad: suma de minutos efectivos de profesionales activos, públicos y reservables, intersectando horario del negocio, horario individual y excepciones.
- Reservado: minutos de reservas `requested`, `pending`, `confirmed` o `completed`, incluyendo buffer global; canceladas/no-show no cuentan.
- Reservas heredadas sin profesional: se multiplican por el número de profesionales porque el scheduler actual las bloquea conservadoramente para todos. Esta limitación evita falsa capacidad disponible.
- Baseline: las 6 ventanas de 7 días equivalentes inmediatamente anteriores, mismos días de semana. Se requieren al menos 4 ventanas con capacidad y 8 reservas históricas.
- Fórmula: `occupancy = min(booked_minutes, capacity_minutes) / capacity_minutes`.
- Señal: ocupación `<= 45 %` y caída de al menos `20 puntos` frente a la media de ratios semanales.
- Severidad: `high` si ocupación `<=25 %` y caída `>=30 pp`; `medium` si ocupación `<=35 %` o caída `>=25 pp`; en otro caso `low`.

No se calcula ocupación por servicio: aunque existe asignación staff/servicio, el catálogo no representa todavía capacidad histórica por servicio con precisión suficiente. La señal es global.

### `high_due_customer_pool`

Reutiliza solamente oportunidades `service_due` activas (`pending`/`actioned`) cuya fecha está dentro del horizonte de 7 días y que no han caducado. Deduplica por cliente, globalmente y por servicio. No replica recurrencia ni guarda IDs/nombres en metadata.

- Negocio: mínimo 5 clientes únicos.
- Servicio: mínimo 4.
- Severidad: `high >=12`, `medium >=8`, `low` en el resto.
- Recomendación: `contact_due_customers` y filtro para abrir las oportunidades existentes.

### `low_return_rate`

Solo usa citas completadas con snapshot explícito de recurrencia. Una fuente “retorna” cuando existe una reserva/visita posterior del mismo cliente y servicio dentro de `interval + window` capturados al completar la fuente.

- Cohorte actual: deadlines de retorno vencidos en los últimos 30 días.
- Baseline: tres periodos previos de 30 días, agregado ponderado por muestra.
- Mínimos: 10 casos actuales y 30 históricos.
- Señal: retorno actual `<=50 %` y caída `>=15 pp`.
- Severidad: `high` si tasa `<=30 %` y caída `>=30 pp`; `medium` si tasa `<=40 %` o caída `>=22 pp`; si no, `low`.

Servicios sin recurrencia no participan. Los seguimientos manuales profesionales siguen siendo oportunidades individuales; nunca originan consejos clínicos o mecánicos.

### `service_demand_drop`

Cuenta reservas recibidas por servicio mediante `created_at`; estados cancelado/no-show quedan fuera. Compara los últimos 30 días con tres periodos anteriores de igual longitud.

- El servicio debe estar activo, reservable, no archivado y existir desde antes del baseline completo.
- Baseline medio mínimo: 5 reservas.
- Señal: periodo actual `<=60 %` del baseline y caída absoluta de al menos 3 reservas.
- Se suprime si la capacidad reciente del negocio es menor al 70 % de la capacidad media histórica, evitando llamar “demanda” a un cierre o reducción sustancial de disponibilidad.
- Severidad: `high <=35 %`, `medium <=50 %`, `low <=60 %` del baseline.

### `seasonal_window`

Solo usa `BusinessCalendarEvent` habilitados y configurados por el negocio. Horizonte: 30 días. Los eventos anuales repiten mes/día y duración; el 29 de febrero cae conservadoramente al 28 en años no bisiestos. Severidad siempre `info`. No se insertan temporadas sectoriales predeterminadas.

## Prioridad temporal

La ocupación analiza únicamente la ventana accionable inmediata (mañana + 7 días), por lo que no eleva alertas de 21 días. `seasonal_window` expone `days_until_start`; futuras versiones pueden ordenar por ese valor sin cambiar la severidad ni usar modelos opacos.

## Ejecución, performance y seguridad

`BusinessGrowthSignalService.evaluate_business()` vive fuera de routers. `run_maintenance.py` reutiliza el job diario con la tarea `growth-signals`, después de `growth-opportunities`. Cada query incluye `business_id`; servicios y eventos se validan contra el tenant. Staff puede leer/descartar señales, pero solo Admin/Owner modifica eventos.

Capacidad precarga settings, profesionales, horarios, excepciones y reservas por ventana. Demanda agrupa un conjunto acotado de 120 días y retorno trabaja sobre bookings del negocio; no hay consultas por cliente. Los índices cubren tenant/estado/severidad, tipo/periodo y eventos activos.

## Integración con Sprint 7, 8A y RRSS futuro

`high_due_customer_pool` expone un filtro estructurado hacia `service_due`. Desde allí el usuario decide `prepare → edit → send`; no se crean mensajes individuales ni acciones automáticas.

El endpoint neutral `GET /growth-signals?status=active` ofrece `type`, `severity`, periodo, servicio, `observed`, `baseline`, explicación y recomendación. Es el contrato de contexto para el flujo futuro:

```text
BusinessGrowthSignal
        ↓
Content Opportunity
        ↓
Format selection (story / reel / carousel)
        ↓
Draft → Approval → Publication
```

Sprint 8B no implementa ninguno de los pasos de contenido ni atribución de campañas. La relación futura prevista es `signal → content/campaign/action → booking`, separada de la atribución individual de Sprint 8A.
