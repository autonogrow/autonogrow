# Integraciones, incidencias y operaciones del panel Owner — Sprint 5C.3

Fecha: 5 de agosto de 2026. Rama: `main`. Base inicial: `ec1cc74`.

## Alcance y estructura anterior

Antes de 5C.3, Integraciones no tenía una vista transversal. Controles comerciales, candidaturas, integración Instagram, capacidades y salud convivían dentro de cada tarjeta extensa de Negocios. Incidencias mostraba campos de proveedor, códigos, referencias y conversaciones en una tarjeta técnica. Colas y worker era una pestaña superior independiente con IDs visibles; Operaciones imprimía un snapshot JSON. Auditoría existía en servidor para las mutaciones, pero no tenía un endpoint Owner de lectura.

El sprint reorganiza el frontend Owner sin modificar backend funcional, modelos, migraciones, endpoints, payloads, permisos, cifrado, idempotencia, locks, reintentos, Business Admin ni créditos. Tampoco inicia 5D.1. La pestaña heredada de colas se conserva como contrato DOM no navegable mientras sus funciones pasan a Operaciones.

## Arquitectura final

```text
Owner
├── Resumen
├── Negocios
├── Altas y aprobaciones
├── Integraciones
│   ├── resumen y filtros
│   ├── lista transversal
│   └── detalle
│       ├── Resumen
│       ├── Control comercial
│       ├── Capacidades
│       ├── Salud
│       ├── Recuperación
│       ├── Candidaturas
│       └── Actividad disponible
├── Incidencias
│   ├── Abiertas
│   ├── Reconocidas
│   ├── Resueltas
│   ├── Todas
│   └── Detalle
├── Operaciones
│   ├── Mensajes y outbox
│   ├── Workers y colas
│   ├── Jobs de integración
│   └── Mantenimiento
└── Auditoría operativa derivada
```

`owner-operations.js` aísla carga, presentación y mutaciones de estas cuatro áreas. Reutiliza estado del Dashboard, helpers de escaping, petición segura, diálogo crítico, detalle de Negocios y revisión de candidaturas de 5C.2.

## Fuentes

| Concepto | Fuente existente | Estado mostrado | Actor | Acción permitida |
|---|---|---|---|---|
| Negocios | `GET /api/owner/businesses` | identidad, slug y contexto | Owner | abrir contexto |
| Control comercial | `GET /api/owner/businesses/{id}/channel-controls` | no permitido, disponible, pendiente, aprobado, suspendido o revocado | Owner/negocio según policy | disponibilidad, aprobar control simulado, suspender, revocar |
| Candidatas Instagram | `GET .../integrations/instagram/oauth/candidates` | solo `candidate_ready` expuesto | Owner decide en Altas y aprobaciones | abrir revisión |
| Candidatas WhatsApp | `GET .../integrations/whatsapp/embedded-signup/candidates` | solo `candidate_ready` expuesto | Owner decide en Altas y aprobaciones | abrir revisión |
| Salud | `GET .../channels/health` | integración, salud, capacidades, reconexión y suscripción | Owner | comprobar, reconectar o reintentar suscripción si procede |
| Jobs Meta | `GET .../channels/jobs` | tipo, estado, fechas y resultado seguro | worker/backend | solo revisar; no hay retry Owner |
| Incidencias | `GET /api/owner/incidents` | estado, severidad, origen derivable, cronología y mensaje seguro | Owner | reconocer, resolver, ignorar o reabrir |
| Outbox/colas | `GET /api/owner/system/queue-status` | agregados, señales de worker y trabajos problemáticos | Owner/worker | reintentar o cancelar estados admitidos |
| Plataforma | `GET /api/owner/system/health` | fuente disponible para actualización operativa | Owner | solo revisar |
| Mantenimiento | `GET/POST /api/owner/system/maintenance...` | estado, motivo y fecha | Owner | activar o desactivar con motivo |
| Auditoría formal | `AuditLog` en servidor, sin GET Owner | no consultable desde frontend | backend | ninguna lectura inventada |

Los snapshots de salud incluyen campos internos en la respuesta Owner. La vista aplica allowlists y omite `integration_id`, proveedor, metadata diagnóstica, códigos, fallos consecutivos, token y caducidad exacta. Los jobs y colas conservan sus IDs exclusivamente en atributos internos necesarios para endpoints; nunca se imprimen.

## Matriz de acciones y riesgo

| Acción | Riesgo | Confirmación | Resultado backend | Refresco |
|---|---|---|---|---|
| Cambiar disponibilidad | medio | recurso, actual, siguiente, consecuencia y motivo | `PUT .../access` | canales, lista, detalle, Dashboard |
| Aprobar control simulado | alto | contextual y con motivo | `POST .../approve` | canales y Dashboard |
| Habilitar/deshabilitar envío | alto | capacidades actual/nueva y motivo | `PATCH .../capabilities` | integración y Dashboard |
| Habilitar/deshabilitar automatización | alto | junto a su valor independiente y motivo | `PATCH .../capabilities` | integración y Dashboard |
| Suspender | alto | destructiva, explica desactivación de capacidades | `POST .../suspend` | integración y Dashboard |
| Revocar | alto | destructiva, explica candidaturas pendientes | `POST .../revoke` | integración y Dashboard |
| Solicitar comprobación | bajo | botón bloqueado durante petición | `POST .../health-check`, idempotente | jobs y detalle |
| Comprobar salud | bajo | sin cambio optimista | job creado o existente | manual posterior y detalle |
| Reconectar Instagram | alto | explica nueva conexión y preservación anterior | URL OAuth validada del backend | redirección segura |
| Reintentar suscripción | medio | contextual; oculto si ya hay job activo del negocio | job idempotente | jobs, salud y detalle |
| Reconocer incidencia | medio | contextual; backend no admite motivo | `PATCH` acknowledge | lista, detalle, Dashboard |
| Resolver incidencia | alto | contextual; backend no admite motivo | `PATCH` resolve | lista, detalle, Dashboard |
| Ignorar incidencia | alto | destructiva visual; no elimina | `PATCH` ignore | lista, detalle, Dashboard |
| Reabrir incidencia | medio | contextual | `PATCH` reopen | lista, detalle, Dashboard |
| Revisar mensaje fallido | bajo | no muta | abre negocio disponible | conserva Operaciones |
| Reintentar mensaje/operación | alto | estado, consecuencia y motivo | endpoint queue retry | Operaciones y Dashboard |
| Cancelar procesamiento | alto | explica que no borra ni marca enviado | endpoint queue cancel | Operaciones y Dashboard |
| Activar mantenimiento | alto | alcance real, estado y motivo | maintenance enable auditado | Operaciones y Dashboard |
| Desactivar mantenimiento | alto | estado y motivo | maintenance disable auditado | Operaciones y Dashboard |
| Revisar job Meta | bajo | no requiere confirmación | solo lectura | ninguno |
| Reintentar job Meta | no disponible | no se ofrece | no existe endpoint Owner seguro | ninguno |

Todas las mutaciones esperan la respuesta del servidor. El diálogo bloquea doble envío, muestra error seguro sin cerrarse, conserva el foco de origen y refresca solo después de confirmación.

## Separación conceptual de Integraciones

Cada fila mantiene visibles y separados: disponibilidad comercial, integración activa, aprobación Owner, envío integrado, automatización y salud. El detalle añade solicitud del negocio, candidatura y reconexión. Las copias explican que conectar no aprueba, aprobar no habilita capacidades, salud no cambia control comercial y una reconexión puede generar una candidata sin sustituir todavía la integración anterior.

El resumen cuenta exclusivamente: integraciones activas, pendientes de revisión, reconexiones necesarias, salud degradada, envío habilitado y automatización habilitada. No calcula uptime, SLA, tasas ni disponibilidad porcentual.

## Filtros, lista y detalle

Los filtros son canal, pendientes, problemas, reconexión, suspendidas y revocadas. La búsqueda local normalizada usa nombre, slug, nombre público de candidata y teléfono redactado; nunca token, scopes o ID.

La lista usa tarjetas adaptables, no tabla horizontal. Muestra negocio/canal, seis capas de estado, recomendación, última comprobación y acciones para abrir integración o candidatura. El detalle presenta resumen, control, capacidades, salud, recuperación, candidaturas y actividad.

Modo asistido aparece como “sin interruptor Owner en el backend actual”. Envío y automatización solo se habilitan en UI cuando control está aprobado, integración activa y salud no está suspendida, revocada ni en error. La comprobación manual deshabilita su botón y respeta la idempotencia del endpoint. WhatsApp delega la reconexión al flujo Embedded Signup canónico de Business Admin; Instagram consume únicamente la URL devuelta y valida protocolo, host y ruta esperados.

## Salud y recuperación

Los estados reales se traducen así: `unknown` aún no comprobada, `healthy` operativa, `warning` con avisos, `degraded` con problemas, `action_required` requiere intervención, `revoked` acceso revocado, `suspended` suspendida y `error` no se pudo comprobar.

Se muestran última/próxima comprobación, reconexión, mensaje seguro y recomendación. No se muestran fallos consecutivos, error code, metadata, Graph response ni intentos técnicos. Una salud sana no oculta capacidades desactivadas.

Recuperación ofrece solo comprobar ahora, reconectar Instagram, abrir reconexión WhatsApp, reintentar suscripción y volver a candidatura cuando los contratos lo permiten. Si hay un `retry_subscription` activo para el negocio, se oculta el botón. Como el job no expone canal, el bloqueo es conservador a nivel de negocio.

## Candidaturas

Integraciones muestra únicamente candidaturas pendientes con canal, negocio, nombre público, creación y garantía de preservación anterior. El backend actual no expone historial Owner de candidaturas resueltas (aprobadas, rechazadas, caducadas, sustituidas o canceladas); la vista lo declara y no inventa resolución ni motivo. Aprobar/rechazar permanece exclusivamente en Altas y aprobaciones.

## Incidencias

Las vistas Abiertas, Reconocidas, Resueltas y Todas usan estados reales. Filtros: estado, severidad, negocio, canal y origen. No se añadió fecha porque el contrato actual no ofrece una consulta fiable desde esta vista. La búsqueda local usa título seguro, negocio y una allowlist de `safe_details`: `message`, `safe_message`, `summary` o `recommendation`.

El origen se traduce a Instagram, WhatsApp, Mensajería, Reservas, Integraciones, Procesamiento o Plataforma solo cuando canal, proveedor, categoría u operación permiten derivarlo. Lista y detalle omiten referencia de incidencia, códigos de proveedor, conversation/message IDs, cuerpos, trazas y metadata.

El detalle separa resumen, impacto confirmado, contexto, cronología e información técnica segura. No infiere usuarios afectados ni responsable. Reconocer, resolver, ignorar y reabrir usan el diálogo común; el backend solo acepta `{action}`, por lo que no se solicita un motivo que se perdería.

## Operaciones, outbox, workers y colas

El resumen combina únicamente fuentes reales y marca cada fallo como “No se pudo comprobar”. Outbox presenta pendientes, reintentos programados, bloqueados y agotados. El endpoint no expone agregados fiables de mensajes en curso, enviados, asistidos, fallidos totales ni claims caducados; la interfaz lo explica y no los muestra como cero.

Los elementos problemáticos se limitan a outbox. Muestran negocio, estado, creación/próximo intento, intentos de forma operativa y acciones existentes. No aparecen outbox/message/provider IDs, destinatario, payload ni error code. “Cancelar procesamiento” no equivale a enviado ni elimina el registro.

Workers muestra actividad, última señal y agregados de colas sin worker ID, versión, PID, trabajo actual, locks o implementación SQL. Un heartbeat ausente se traduce como “No se pudo comprobar”, no como detenido. El contrato no permite inferir retraso creciente ni claims expirados.

## Jobs de integración

Los tipos `health_check`, `retry_subscription` y `attempt_cleanup` se traducen a comprobación de salud, reintento de suscripción y limpieza de intentos caducados. Se muestran negocio, estado, creación, próxima ejecución y resultado seguro. El endpoint de listado no expone el canal; la vista no lo inventa. Tampoco expone una mutación segura para retry, de modo que el panel lo declara y no añade botón.

## Mantenimiento

La tarjeta muestra estado, motivo y fecha del último cambio. No hay actor en la respuesta segura. El backend no describe con precisión qué subsistemas se pausan, por lo que la copia remite al alcance real del middleware y evita prometer que se vacían colas, se detienen todos los workers o se ejecutan backups. Activar/desactivar exige motivo, confirmación, respuesta y refresco; la auditoría de backend existente permanece intacta.

## Auditoría operativa

`AuditLog` registra actor, entidad, acción y metadata, pero no existe un endpoint Owner de lectura. Para no inventar contrato, la pestaña se etiqueta como actividad operativa derivada y compone solo hitos confirmados ya consultables: fechas de aprobar/suspender/revocar controles, cambios de incidencia, resultados terminales de jobs y último cambio de mantenimiento.

Se puede filtrar por negocio y tipo. Fecha, actor, entidad y resultado detallado no se ofrecen porque la fuente no los proporciona uniformemente. Cada evento con negocio puede abrir su contexto. Un aviso permanente diferencia esta vista de la auditoría formal.

## Errores parciales y estado

Integraciones diferencia fuente completa, parcial, error y vacío; un fallo total no produce seis ceros. Operaciones carga queue, health, jobs y mantenimiento de forma independiente: un fallo de jobs no borra outbox, uno de queue no borra mantenimiento y uno de auditoría derivada no rompe Operaciones. Los últimos datos válidos del Dashboard se conservan donde su cargador ya lo soporta.

Los filtros, selección y sección de detalle viven en estado del módulo y se conservan durante refresh. Las acciones no cierran diálogos por respuestas fallidas.

## Polling, concurrencia y rendimiento

Antes del sprint el Owner no tenía `setInterval` ni polling periódico. 5C.3 no añade polling. Hay actualización manual, refresh tras mutación, single-flight para Integraciones/Operaciones y versionado heredado en fuentes del Dashboard. Health check y suscripción descansan además en idempotencia persistente backend.

Las llamadas por negocio se procesan en lotes de cuatro. Se reutilizan snapshots del Dashboard cuando están listos. El listado de jobs sigue siendo N×negocios por ausencia de endpoint agregado; es deuda documentada, no motivo para inventar API.

## Navegación contextual

- Dashboard abre integración exacta por negocio/canal, incidencia por ID interno no visible y Operaciones/mensajes.
- Negocio abre Integraciones conservando su detalle y selección.
- Integración abre negocio, filtra incidencias asociadas o vuelve a la candidata en Altas y aprobaciones.
- Incidencia abre negocio, integración o Operaciones cuando existe contexto seguro.
- Operación y evento de auditoría derivada abren negocio cuando el backend aporta asociación.

Los IDs se codifican para peticiones y atributos; no se imprimen. URLs Admin usan slug codificado y `rel=noopener`; OAuth solo navega a la URL HTTPS de Instagram validada.

## Responsive y accesibilidad

La estructura estática cubre 360×800, 390×844, 768×1024, 1024×768, 1280×800 y 1440×900 mediante seis/tres/dos/una columna. A 767 px, filtros, estados, detalles, filas y acciones se apilan sin tabla ni overflow global. La navegación secundaria puede desplazarse dentro de su propio eje. El diálogo existente usa `100dvh`, safe area y acciones apiladas.

Se conservan `h1`, landmarks, skip link, `aria-current`, labels, botones nativos, listas semánticas, `aria-busy` por fuente, estados textuales, foco visible, trap, Escape, retorno de foco y reduced motion. Las listas no son live regions; solo feedback de acciones y estados de actualización solicitada se anuncian.

## Seguridad

El gate `is_owner` y la autorización de servidor no cambian. Toda interpolación externa nueva pasa por `escapeHtml`; errores HTTP se traducen localmente. No se registran URLs, cuerpos ni respuestas. La pantalla omite access/refresh token, secretos, verify token, state/hash/fingerprint, WABA/phone/account IDs, provider/outbox/message/job/claim IDs visibles, idempotency keys, locks, payload, metadata, traceback, SQL y Graph response.

El módulo no construye OAuth, no solicita credenciales, no cambia estado local antes de backend, no aprueba candidaturas, no reintenta jobs Meta sin endpoint, no vacía colas, no elimina datos y no ejecuta consultas arbitrarias.

## Pruebas

`backend/tests/test_owner_integrations_operations.py` fija arquitectura, separación conceptual, indicadores, filtros, lista/detalle, controles, capacidades, salud, recuperación, candidaturas, incidencias/acciones, outbox, workers/colas, jobs, mantenimiento, auditoría derivada, errores parciales, polling, navegación, escaping, URLs, secretos, IDs visibles, gate Owner, DOM, responsive, accesibilidad y documentación.

Se ejecutaron además shell, Dashboard, Negocios/aprobaciones, suites funcionales relacionadas, Ruff, `git diff --check` y la suite completa. No se relajaron expectativas salvo la pestaña superior Colas, actualizada al contrato 5C.3 que la integra en Operaciones.

Resultados:

- shell + 5C.1 + 5C.2 + 5C.3: 87 pruebas superadas;
- suites funcionales relacionadas: 191 pruebas y 36 subtests superados, 26 omitidos;
- `ruff check backend/tests`: sin incidencias;
- suite completa: 553 pruebas y 53 subtests superados, 26 omitidos;
- 8.259 avisos preexistentes, principalmente deprecaciones de fecha/hora y SQLAlchemy; no se ocultaron ni se modificaron fuera de alcance;
- sintaxis de los tres scripts Owner y `git diff --check`: sin errores.

## Limitaciones, deuda y validación visual pendiente

No hubo sesión Owner autenticada ni datos reproducibles y no se alteró la base. La validación visual autenticada queda pendiente para QA final:

1. 1440 × 900 — integraciones;
2. 1440 × 900 — detalle y salud;
3. 1440 × 900 — incidencias;
4. 1440 × 900 — operaciones;
5. 1440 × 900 — auditoría;
6. 1024 × 768 — jobs y mantenimiento;
7. 768 × 1024 — detalle;
8. 390 × 844 — integración;
9. 390 × 844 — incidencia;
10. 390 × 844 — operaciones;
11. 360 × 800 — confirmación crítica o error;
12. zoom 200/400 %, teclado y NVDA/VoiceOver.

Deuda explícita:

- endpoint Owner agregado para integraciones/jobs sin N×negocios;
- endpoint seguro de lectura de AuditLog, con política de redacción;
- historial Owner de candidaturas resueltas;
- canal en el serializer de jobs Meta;
- agregados reales de outbox (en curso, enviados, asistidos y fallidos totales) y claims caducados;
- defensa backend transaccional para capacidades condicionadas a salud si producto la requiere;
- harness E2E autenticado y matriz visual final.

El siguiente trabajo recomendado es el QA Owner transversal/autenticado planificado, no 5D.1.
