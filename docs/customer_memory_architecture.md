# Customer Memory — arquitectura V1

## Finalidad y límites

Customer Memory conserva contexto reutilizable que un negocio necesita para atender a un cliente: preferencias declaradas, interés en servicios, disponibilidad, notas operativas y un resumen breve de la relación. No sustituye `Customer`, reservas, servicios, conversaciones ni oportunidades; por eso no duplica nombre, teléfono, email, precio, historial completo o próxima cita.

Tampoco es un expediente médico, un CRM completo, un perfil psicológico ni un sistema de scoring. V1 no usa LLM, embeddings, búsqueda semántica, recomendaciones clínicas, campañas ni automatización de mensajes.

## Entidad persistente

`CustomerMemoryItem` contiene `business_id`, `customer_id`, categoría, `key`, valor tipado, fuente y referencia de origen opcional, confianza, estado, marca sensible, actor y timestamps de ciclo de vida. El valor se almacena en una columna textual; no existe un JSON indiscriminado. Los índices cubren negocio, cliente, estado, categoría y key.

Las categorías V1 son:

- `preference`
- `service_interest`
- `availability_preference`
- `operational_note`
- `relationship`
- `other`

Las fuentes preparadas son `manual`, `booking`, `service_history`, `conversation` y `system`. La API Admin de V1 solo acepta `manual`; `booking`/`service_history`/`system` quedan disponibles para hechos deterministas futuros y `conversation` está reservado, sin extracción automática. Una memoria manual usa confianza `1.0`; la UI no muestra este dato técnico.

## Hechos, derivados e inferencias

Hay tres planos separados:

1. Memoria explícita: un profesional escribe “Prefiere viernes por la tarde”. Se persiste, identifica como `manual` y es editable.
2. Resumen derivado: “servicio más frecuente” se calcula de reservas completadas. No se persiste como preferencia ni se denomina “favorito”.
3. Inferencia futura: una IA podría proponer “parece preferir tardes”. V1 no la ejecuta ni la guarda.

## Lifecycle y sustitución

Los estados son `active`, `superseded`, `expired` y `deleted`. Las lecturas activas excluyen cualquier elemento vencido y actualizan su estado a `expired`; el histórico se conserva. `DELETE` es lógico y conserva timestamps/auditoría. “Obsoleta” mueve una memoria activa a `superseded` sin crear una nueva.

Una sustitución exige señalar el item anterior. La nueva fila conserva exactamente la misma categoría y key, la anterior registra `superseded_at`/`superseded_by_id` y ambas quedan trazables. No se interpreta automáticamente que dos textos libres sean contradictorios y no existe unicidad que elimine intereses o notas paralelas.

Al borrar un `Customer`, la FK `ON DELETE CASCADE` y la relación ORM eliminan su memoria con la misma semántica, evitando huérfanos. Si se implanta un flujo general de anonimización/exportación GDPR, debe incorporar esta tabla; hoy no hay un subsistema general que ampliar y queda como deuda transversal.

## Resumen derivado

`CustomerMemoryService.summary` consulta únicamente reservas estructuradas del mismo negocio y cliente. Solo usa estado `completed`; excluye canceladas, rechazadas, no-show y filas sin fecha real de visita. Devuelve:

- número de visitas;
- fecha y servicio de la última visita;
- servicio más frecuente, con recuento;
- intervalo de retorno observado;
- recurrencia explícita capturada en snapshots cuando existe.

En empate de servicio gana el visto más recientemente; después se estabiliza por nombre e id. El intervalo observado necesita cuatro visitas y tres diferencias positivas. Se calcula con la mediana de días entre visitas consecutivas y se redondea al día más cercano, reduciendo el efecto de outliers. Se etiqueta “Comportamiento observado”. Una recurrencia configurada y capturada en la reserva tiene prioridad informativa y el comportamiento nunca la sustituye ni se usa todavía para recomendar tratamientos o servicios.

Abrir una ficha no recorre conversaciones. El resumen consulta reservas indexadas por negocio/cliente/estado. La lista de oportunidades carga memorias activas en bloque y limita el contexto a dos elementos.

## API y permisos

Los endpoints tenant-scoped son:

- `GET/POST /api/admin/businesses/{slug}/customers/{customer_id}/memory`
- `GET /api/admin/businesses/{slug}/customers/{customer_id}/memory-summary`
- `PATCH/DELETE /api/admin/businesses/{slug}/customer-memory/{id}`
- `POST /api/admin/businesses/{slug}/customer-memory/{id}/supersede`
- `POST /api/admin/businesses/{slug}/customer-memory/{id}/obsolete`

Owner, admin y staff activo reutilizan `require_business_access`, coherente con la gestión actual de clientes. Cada query comprueba `business_id`; un customer o memory id cruzado produce 404 y no revela la existencia del recurso.

## Privacidad, seguridad y auditoría

La UI advierte que no se guarden contraseñas, tokens, credenciales, tarjetas completas ni información clínica innecesaria. El backend rechaza términos claros de credenciales, material PEM y números completos que superen Luhn. `is_sensitive` permite señalar contexto privado, pero no autoriza expedientes médicos ni perfiles de salud, religión, política, orientación sexual, raza/etnia, finanzas, intimidad o menores.

Se auditan creación, modificación, sustitución/obsolescencia y borrado con actor, negocio, customer id, categoría, key, fuente y timestamps. El valor nunca se copia al audit log. Los logs de aplicación tampoco deben incluir payloads de memoria.

Growth no cambia ninguna regla. El detalle de una `CustomerOpportunity` puede consultar un resumen compacto y la lista añade como máximo dos memorias activas no sensibles. Una memoria sensible, expirada o borrada no sale de la ficha privada, y jamás se mezcla otro tenant. Sprint 8C no inserta automáticamente ese contexto en un mensaje ni decide una acción sensible.

Para RRSS deben mantenerse dos dominios: el contexto individual sirve solo para atención/seguimiento privado; una futura señal de negocio requerirá agregación, umbrales y anonimización antes de contenido público. V1 no implementa esa agregación.

## Extracción futura desde conversaciones

No se crea `CustomerMemoryCandidate` porque V1 no la consume. El flujo futuro documentado es:

```text
mensaje entrante
  -> detección de información potencialmente reutilizable
  -> extracción estructurada y clasificación
  -> confidence y deduplicación
  -> candidato revisable
  -> revisión humana o política de autoaceptación por categoría
  -> CustomerMemoryItem
```

La IA no escribirá directamente verdad permanente. Podrá proponer horarios/días, servicios mencionados, intereses, preferencias estéticas o restricciones operativas simples. No deberá inferir categorías sensibles, diagnósticos, salud, religión, política, orientación sexual, raza/etnia, finanzas, intimidad ni datos de menores.
