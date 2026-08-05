# Dashboard operativo del panel Owner — Sprint 5C.1

Fecha: 5 de agosto de 2026. Rama: `main`. Base inicial: `5ee91e7`.

## Alcance

El Dashboard Owner pasa de ser una fila global de seis contadores situada sobre Negocios a una sección `Resumen` independiente. El trabajo se limita al resumen ejecutivo y operativo: las tarjetas extensas de negocio, el onboarding, Incidencias, Colas y worker y Operaciones conservan sus contratos y mutaciones. No se añadió backend funcional, modelo, migración, endpoint, permiso ni regla de aprobación.

Las validaciones autenticadas, E2E, visuales, zoom, lectores de pantalla y cambio entre dos negocios quedan aplazadas al QA final por decisión de planificación. La falta de una sesión reproducible no bloqueó las comprobaciones estáticas y automáticas.

## Estructura anterior

La entrada Owner abría `Negocios`. Encima aparecían Total negocios, Negocios activos, Reservas pendientes, Mensajes pendientes, Reseñas pendientes e Incidencias abiertas. No existía una pantalla propia para responder qué debía decidir el Owner. Candidaturas, salud, usuarios, marca y automatización vivían en subpaneles de cada tarjeta; Incidencias, colas y salud global estaban en pestañas separadas.

La carga de Negocios renderizaba además todos sus editores y provocaba peticiones por cada negocio aunque el Owner solo quisiera supervisar excepciones.

## Arquitectura final de 5C.1

```text
Owner
├── Resumen (nuevo, inicial)
│   ├── indicadores operativos
│   ├── Necesita tu decisión
│   ├── Integraciones que necesitan atención
│   ├── Incidencias
│   ├── Procesamiento de mensajes
│   ├── Negocios que necesitan atención
│   ├── Estado general
│   └── Actividad reciente
├── Negocios (heredado)
├── Nuevo negocio (heredado)
├── Incidencias (heredado)
├── Colas y worker (heredado)
└── Operaciones (heredado)
```

La arquitectura futura `Altas y aprobaciones`, `Integraciones` y `Auditoría` no se materializa con páginas vacías. Sus vistas completas pertenecen a 5C.2 y 5C.3. El Dashboard enlaza por ahora al subpanel existente y preciso de Negocios, o a la sección heredada correspondiente.

## Fuentes de datos reales

| Fuente | Endpoint existente | Uso en Resumen | Definición |
| --- | --- | --- | --- |
| Negocios | GET `/api/owner/businesses` | activos, altas, atención, creación reciente | `status`, `created_at`, `metrics` y `health` calculados por backend |
| Controles de canal | GET `/api/owner/businesses/{id}/channel-controls` | aprobación, entrega, automatización y actividad | estados comerciales/capacidades canónicos |
| Candidaturas Instagram | GET `.../integrations/instagram/oauth/candidates` | decisiones pendientes y actividad | solo candidaturas `candidate_ready` devueltas por backend |
| Candidaturas WhatsApp | GET `.../integrations/whatsapp/embedded-signup/candidates` | decisiones pendientes y actividad | solo candidaturas `candidate_ready` |
| Salud Meta | GET `/api/owner/businesses/{id}/channels/health` | integraciones con atención | `health_status`, reconexión y última comprobación |
| Incidencias | GET `/api/owner/incidents?limit=30` | abiertas/críticas y actividad | estados y severidad formal del sistema |
| Procesamiento | GET `/api/owner/system/queue-status` | reintentos, bloqueos, casos agotados y worker | contadores agregados existentes |
| Plataforma | GET `/api/owner/system/health` | API/datos, workers, alertas y actualización | señal compacta ya existente, no SLA |

No existe un endpoint Owner de auditoría consultable ni un endpoint agregado de Dashboard. La actividad reciente se limita por tanto a eventos fechados ya presentes en las respuestas: creación de negocio, candidatura, aprobación/suspensión/revocación de canal e incidencia creada/resuelta. No pretende sustituir Auditoría.

## Indicadores

Se muestran seis indicadores reales: Negocios activos, Altas pendientes (`draft`, `onboarding`, `configuration_pending` o `ready`), Decisiones pendientes, Integraciones con problemas, Incidencias abiertas y Problemas de mensajes. Los tres primeros agregan exclusivamente las respuestas anteriores; problemas de mensajes suma fallos, reintentos, bloqueos y casos agotados, no el volumen normal pendiente.

No se muestran ingresos, MRR, ARR, churn, conversión, crecimiento porcentual, satisfacción, ahorro, disponibilidad ni SLA. Los seis contadores heredados permanecen en Negocios para conservar su contrato DOM y el contexto histórico de esa sección.

## Decisiones pendientes

El bloque prioritario agrega candidaturas Instagram/WhatsApp `candidate_ready` y controles `pending_approval` que no tengan ya una candidatura equivalente. Cada fila presenta negocio, canal/tipo, estado, fecha, motivo traducido y `Revisar solicitud`.

No hay botones de aprobar o rechazar en Resumen. La acción abre la tarjeta de negocio y su detalle de canal/integración; el proceso canónico conserva revisión, motivo y endpoint original. El resumen no presenta cuenta externa, número Meta, scopes, tokens, payloads ni identificadores de intento.

## Integraciones

Se consideran de atención `warning`, `degraded`, `action_required`, `revoked`, `suspended`, `error` o `reconnection_required`. Cada elemento separa:

- aprobación comercial;
- capacidad de envío;
- capacidad de automatización;
- salud operativa;
- última comprobación;
- recomendación y destino de revisión.

No se colapsan las capas en un único “Activo” y no se renderizan mensajes de error técnicos, metadata de diagnóstico ni identificadores de proveedor.

## Incidencias y operaciones

Incidencias usa únicamente severidad y estado formales. El título se traduce desde categorías conocidas o cae en una descripción operativa por canal; se muestran negocio, severidad, estado y última fecha. Referencias, códigos del proveedor, conversaciones, mensajes y detalle seguro interno quedan en la vista heredada, no en Resumen.

Procesamiento suma señales de inbox/outbox existentes y traduce worker, retry, dead letter y blocked a lenguaje de impacto. Los pendientes normales se informan sin clasificarlos como fallo. No aparecen job ID, intentos internos, locks, PID, SQL ni JSON.

## Negocios y plataforma

La atención de negocio usa hechos disponibles en el resumen de `/businesses`: estado no activo, información básica, servicios activos, horario y teléfono. No se afirma que falten administradores porque esa comprobación exigiría otra carga por negocio y no forma parte de la respuesta agregada.

Estado general no promete disponibilidad. Una respuesta satisfactoria de `/system/health` permite indicar que API/datos respondieron; se cruza con procesamiento, integraciones e incidencias críticas. Cuando una fuente falta se muestra `No se pudo comprobar`, no `Operativo`.

## Estados vacíos y errores parciales

Cada bloque tiene carga, vacío real, error y comprobación parcial. Los vacíos específicos incluyen:

- `No hay decisiones pendientes`;
- `No hay integraciones que requieran atención`;
- `No hay incidencias abiertas`;
- `El procesamiento no presenta problemas detectados`.

Si una petición falla y existe un snapshot válido, el DOM conserva ese snapshot y lo marca como anterior. Si nunca hubo datos, muestra `Fuente no disponible`. Una respuesta parcial por negocios explica cuántos no se pudieron comprobar. Cada bloque ofrece reintento de su fuente; un fallo de canales no borra incidencias y un fallo de plataforma no cambia Negocios.

## Actualización y concurrencia

La inspección confirmó que Owner no tenía polling antes de 5C.1: no había `setInterval`, `setTimeout`, backoff ni ciclo condicionado por visibilidad. El botón Actualizar era una carga manual de negocios/incidencias y, si se habían abierto, colas. Por tanto no había polling que reutilizar y este sprint no inventa uno.

Resumen reutiliza el botón manual y los GET existentes. Una actualización global es single-flight; una segunda solicitud durante la primera se agrupa en una sola repetición. Cada fuente tiene versión y descarta respuestas obsoletas. Los controles por negocio se consultan en lotes de cuatro negocios para evitar una ráfaga sin límite. No se crean intervalos duplicados, no se cambia la sección activa, no se reinicia el scroll y no se cierran detalles.

La dependencia por negocio sigue siendo deuda hasta que exista un agregado backend aprobado. 5C.1 reduce el coste inicial al no renderizar usuarios, media y automatización de todas las tarjetas mientras el Owner permanece en Resumen; esos editores se cargan al abrir Negocios.

## Navegación contextual

Las acciones no recargan la aplicación:

- candidatura/integración → Negocios y detalle de canal/integración;
- negocio incompleto → tarjeta de Negocios;
- incidencia → Incidencias;
- fallo de mensaje → Colas y worker;
- salud global → Operaciones;
- alta pendiente → Nuevo negocio.

El identificador validado por la respuesta backend se conserva solo en `data-*` para localizar la tarjeta y construir la petición heredada; no se imprime como contenido. La navegación restaura `aria-current`, abre el `<details>` correcto, mueve foco y respeta movimiento reducido.

## Responsive y accesibilidad

La estructura cubre 360×800, 390×844, 768×1024, 1024×768, 1280×800 y 1440×900 mediante seis, tres, dos o una columna según espacio. A 767 px el contenido pasa a una columna; a 399 px también apila cada indicador, capas y acciones. Se reutilizan drawer, safe area, foco visible y `prefers-reduced-motion` compartidos.

El gate y la aplicación autenticada son mutuamente excluyentes y cada uno conserva un `h1`. Resumen usa `h2`/`h3`, landmarks nativos, botones, `aria-current`, `aria-busy` por bloque y foco programático para destinos. Solo el estado de sincronización iniciado por el usuario es `role=status`; los bloques no son live regions, evitando anuncios repetidos si en el futuro se incorpora polling.

## Seguridad y rendimiento

El gate `is_owner`, credenciales/CSRF, 401/403 y endpoints protegidos permanecen intactos. Todas las interpolaciones externas nuevas pasan por `escapeHtml`; los errores del Dashboard son mensajes locales genéricos. No se registran respuestas ni se insertan URLs externas.

La pantalla no ejecuta mutaciones. Aprobación, suspensión, revocación, capacidades, automatización, créditos, mantenimiento y jobs permanecen en sus flujos originales. La carga inicial evita los editores completos de Negocios; usa single-flight, versiones y lotes limitados. No se añadió framework, bundler o dependencia.

## Pruebas

`backend/tests/test_owner_dashboard.py` fija estructura, seis indicadores, ausencia de métricas ficticias, decisiones sin aprobación directa, capas de integración, incidencias, operaciones, atención de negocio, actividad real, vacíos, errores parciales, snapshot anterior, single-flight, ausencia de polling nuevo, navegación, permisos, secretos, escaping, endpoints, contratos DOM, responsive y accesibilidad.

También se ejecutaron shell compartido, suites Owner/backend relacionadas, Ruff, `git diff --check` y suite completa.

Resultados finales:

- Dashboard + shell: 21 pruebas superadas;
- suites funcionales relacionadas con Owner, onboarding, roles, canales, Meta, salud, incidencias, colas, automatización y operaciones: 225 pruebas superadas, 1 omitida y 36 subtests superados;
- `ruff check backend/tests`: sin incidencias;
- suite completa: 487 pruebas y 53 subtests superados, 26 omitidos;
- 8301 avisos preexistentes, principalmente deprecaciones de fecha/hora y SQLAlchemy; no se ocultaron ni se modificaron fuera de alcance;
- `git diff --check`: sin errores (Git solo informa de la conversión de LF a CRLF propia de este checkout).

## Limitaciones y validación visual pendiente

No se fabricaron datos, sesión ni capturas. Pendiente en QA final con sesión Owner reproducible:

1. 1440×900 con decisiones, integraciones degradadas e incidencias;
2. 1024×768 con negocios que requieren atención;
3. 768×1024 general;
4. 390×844 para decisiones e incidencias;
5. 360×800 para vacío/error parcial;
6. zoom 125/150/200/400 %, reflow y contraste;
7. teclado, NVDA/VoiceOver y retorno de foco;
8. cartera de 10+ negocios y dos negocios con respuestas lentas.

## Deuda restante

- Endpoint agregado Owner para evitar la composición N×negocios, sujeto a diseño backend separado.
- Vista transversal de Altas y aprobaciones (5C.2).
- Lista compacta/ficha de negocio y deep links persistentes (5C.2).
- Vista completa de Integraciones e Incidencias orientada a impacto (5C.3).
- Endpoint/vista de Auditoría aprobados; no se inventaron en este sprint.
- Sustitución de prompts/confirmaciones heredados por diálogos accesibles.
- Harness E2E autenticado y validación visual final.

El siguiente sprint recomendado es 5C.2, una vez ejecutado el QA visual/autenticado planificado para este cierre. No se inició trabajo de 5C.2.
