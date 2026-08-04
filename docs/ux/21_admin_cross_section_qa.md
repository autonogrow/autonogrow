# QA transversal del Business Admin — Sprint 5F.0

Fecha: 5 de agosto de 2026. Rama: `main`. Base auditada: `7b74c64`.

## Alcance y criterio

La revisión cruza los seis rediseños del Business Admin: Dashboard, Agenda, Clientes y conversaciones, Configuración, Canales y automatizaciones, y Crecimiento y reseñas. Se conservaron modelos, migraciones, endpoints, payloads, permisos, reglas de negocio y contratos heredados. No se inició trabajo sobre Owner.

El objetivo de esta pasada es detectar regresiones transversales y corregir solo defectos reproducibles en el código. Una comprobación estática o automatizada no se presenta como validación visual autenticada.

## Metodología

1. Se comprobó que `main` estaba limpio y situado en el commit esperado.
2. Se inspeccionaron por completo `index.html`, `styles.css`, `admin.js`, el shell compartido y la documentación 13–20.
3. Se inventariaron navegación, hashes, loaders, polling, versiones de carga, fingerprints, formularios dirty, modales, listeners, interpolaciones HTML, URLs y rutas tenant-scoped.
4. Se cruzaron las llamadas críticas con los filtros por `business_id` del backend.
5. Se creó una prueba estática transversal que fija los contratos encontrados.
6. Se intentó preparar una validación autenticada sin modificar datos. La base local no contiene usuarios y no está al nivel del esquema actual; tampoco había un backend reproducible ni dos negocios autorizados. No se migró ni se sembró la base.

## Matriz transversal

`E` significa evidencia estática y automatizada; `P` significa pendiente de sesión real.

| Área | Carga | Vacío | Error | Mutación | Polling | Dirty state | Responsive | Accesibilidad |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Dashboard | E: estados por fuente | E: bloques propios | E: reintento parcial | E: destinos reales | E: deriva de loaders | N/A | E / P visual | E: `h2`, busy, live moderado |
| Agenda | E: skeleton y estado | E: por vista/filtro | E: conserva snapshot válido | E: guardas por booking | E: 15/30 s | E: borrador de notas preservado | E / P visual | E: tabs, foco, modal |
| Clientes | E: deriva de conversaciones | E: panel explícito | E: parcial | E: sin acción duplicada | E: 10/15 s | N/A | E / P visual | E: controles nativos |
| Conversaciones | E: lista y detalle separados | E: lista/detalle | E: no borra snapshot previo | E: guards de envío/estado | E: lista 10/15 s; hilo 5/15 s | E: borrador/scroll/foco | E / P visual | E: drawer contextual y teclado |
| Configuración | E: loaders independientes | E: por categoría | E: feedback por formulario | E: claves de mutación | E: no la repinta | E: snapshots delegados | E / P visual | E: labels, errores y foco |
| Canales | E: onboarding/health separados | E: no disponible | E: fuentes parciales | E: acciones bloqueadas | E: solo refresh solicitado | E: plantillas/reglas | E / P visual | E: navegación contextual |
| Automatizaciones | E: settings/templates | E: sin reglas | E: conserva datos | E: guardas por clave | E: 15/30 s indirecto | E: formulario y reglas | E / P visual | E: feedback por acción |
| Crecimiento | E: espera fuentes | E: condición real | E: lista de fuentes fallidas | E: navegación contextual | E: reutiliza operations | N/A | E / P visual | E: estructura y estados textuales |
| Reseñas | E: request + outbox | E: clientes/solicitudes | E: parcial y sin falso retry | E: idempotencia/guards | E: 15/30 s | N/A | E / P visual | E: acciones nativas y feedback |

## Navegación principal y secundaria

La navegación principal conserva cinco destinos visibles y los tabs heredados ocultos. `showAdminSection` calcula el padre de Configuración, Canales o Crecimiento y ahora actualiza `aria-current` de forma síncrona junto con clase y `aria-selected`. Así no depende del `MutationObserver` del shell para corregir un estado transitorio.

Una categoría desconocida cae en Resumen y ahora normaliza el hash a `#summary`. Los hashes válidos, el parámetro `b`, los deep links de reserva y la recarga permanecen intactos. El drawer compartido conserva `inert`, Escape, backdrop y retorno de foco. En móvil, Inicio, Agenda y Mensajes son accesos directos; Más abre el drawer.

Las navegaciones secundarias calculan su propio `aria-current` desde la sección activa. Los destinos contextuales comprobados son:

- Dashboard → Agenda/Pendientes, Conversaciones, Canales y Crecimiento/Reseñas.
- Agenda → Reseñas.
- Crecimiento → Configuración/Información y el campo de enlace de reseñas.
- Crecimiento → el canal concreto, incluido WhatsApp.
- Canales y Crecimiento → Respuestas automáticas.

No se modifica la sección activa durante un refresh de fondo ni al cerrar los dos modales existentes.

## Cambio de negocio y autenticación

El Business Admin no ofrece un selector de negocio en documento: el contexto se resuelve desde `?b=slug`, se autoriza contra `getMe().businesses` y un cambio de URL produce una carga completa del documento. La aplicación parte oculta, por lo que la nueva carga no reutiliza el DOM del negocio anterior. Todas las cargas del panel se reconstruyen con el slug actual; el estado temporal de media en `sessionStorage` también incluye y comprueba el slug.

En servidor, reservas y conversaciones vuelven a filtrarse por `business_id`; la validación frontend no sustituye ese control. Las versiones de carga descartan respuestas obsoletas dentro del documento.

Queda pendiente la prueba dinámica exigente entre dos negocios autorizados. La base local devolvió cero usuarios y no pudo representar dos membresías. Por tanto, no se afirma haber observado en navegador la ausencia de un frame transitorio entre tenants.

## Polling y estabilidad de estado

No se añadió polling. Hay tres tareas persistentes, programadas con `setTimeout` y no con `setInterval`:

| Tarea | Visible | Documento oculto | Propósito |
| --- | ---: | ---: | --- |
| `conversationThread` | 5 s | 15 s | Actualizar únicamente la conversación seleccionada |
| `conversationList` | 10 s | 15 s | Actualizar lista, contadores y prioridades |
| `operations` | 15 s | 30 s | Reservas y, para Admin, outbox y solicitudes de reseña |

Cada tarea usa `inFlight`, `rerunRequested`, timeout único y backoff exponencial limitado a ×4. `startAdminPolling` es idempotente; ocultar la pestaña reprograma y volver a mostrar solicita un refresh. Los loaders críticos tienen versiones, fingerprints y descarte de respuestas antiguas. Agenda conserva borradores de notas, foco, selección y scroll; Conversaciones conserva borrador, conversación activa y posición. Los formularios de automatización y plantillas no se repintan cuando están dirty.

Se retiró `aria-live` del indicador de sincronización, del recuento de conversaciones y del panel de reservas porque cambian por polling. El live region dedicado de Dashboard se mantiene: usa fingerprint y solo anuncia un cambio material o un error nuevo.

## Formularios y dirty state

Información, página pública, servicios existentes/nuevo, equipo existente/nuevo, horario, excepción, plantillas, automatización y reglas usan snapshots por `data-config-dirty-key`. Los listeners de `input` y `change` están delegados una sola vez en el contenido principal. Se excluyen archivos, campos deshabilitados y campos marcados `data-ignore-dirty`.

El sistema distingue sin cambios, cambios sin guardar, mutación en curso, guardado y error. Una respuesta fallida no actualiza el snapshot. Cambiar desde una sección dirty de Configuración o Canales solicita confirmación, y `beforeunload` cubre el cierre accidental. Las claves de mutación evitan guardados dobles. La comprobación visual de múltiples formularios sucios y cambio real entre negocios queda pendiente.

## Modales y confirmaciones

Los dos diálogos DOM —reagendar y bloqueo al eliminar profesional— tienen `role=dialog`, `aria-modal`, título y descripción. Comparten manejo de Escape y focus trap; ambos almacenan y restauran el foco. Reagendar admite cierre por backdrop; el diálogo destructivo de profesional exige una acción explícita, decisión deliberada.

Las demás confirmaciones son diálogos nativos asociados a un gesto. Los conjuntos de mutación y estados `aria-busy` evitan dobles acciones. Se eliminó del diálogo de profesional el teléfono completo y el texto visible `Reserva #…`; el ID permanece exclusivamente en el handler interno para abrir la cita correcta.

## Revisión por área

### Dashboard

Los contadores derivan de reservas y conversaciones cargadas. El estado del negocio cruza publicación, servicios, disponibilidad y salud de canales. Las fuentes parciales tienen retry independiente y no fuerzan “Todo funciona”. Reseñas produce una alerta priorizada y no duplicada. No hay conversión, ingresos, ROI, rating ni otras métricas inventadas.

### Agenda

Hoy, Pendientes, Semana, próximas e historial se derivan de la misma colección y conservan filtros, fecha y profesional. Las acciones se generan por estado y `bookingMutationIds` bloquea dobles mutaciones. Reagendar descarta huecos obsoletos por versión y fecha solicitada. Notas, adjuntos y reseñas comparten el refresh operativo. Los errores de notas y cambio de estado ahora pasan por el filtro seguro.

### Clientes y conversaciones

Lista, hilo y ficha contextual tienen loaders/versiones separados. El polling no sustituye una conversación seleccionada por otra ni borra el borrador. El modo asistido no se marca como enviado. Teléfonos se muestran solo donde son dato operativo de contacto; el outbox los enmascara. Los errores de conversación pasan ahora por el mismo filtro que rechaza trazas, SQL, payloads y tokens.

### Configuración

Las seis categorías mantienen fuentes y formularios independientes. Los fallos de galería, personal o disponibilidad no destruyen los demás bloques. URLs públicas y media se validan con protocolos permitidos. El log de media ya no incluye URL ni cuerpo de respuesta. No se alteró la fuente canónica del enlace de reseñas.

### Canales y automatizaciones

La interfaz conserva por separado disponibilidad comercial, conexión, aprobación, entrega, automatización y salud. El Business Admin puede iniciar/reconectar los flujos permitidos, pero no aprobar, suspender, revocar ni activar capacidades Owner. `waba_id` y `phone_number_id` solo forman parte del payload necesario al completar Embedded Signup; no se renderizan. No aparecen tokens, secretos, scopes o metadata.

### Crecimiento y reseñas

Elegibilidad, solicitudes y actividad se derivan de reservas, `ReviewRequest` y outbox existentes. Preparar, copiar, abrir, marcar y omitir reutilizan el estado canónico y actualizan Agenda, Dashboard y Crecimiento. No se afirma entrega ni reseña recibida, no hay envío integrado y no se inventa retry. IDs de booking, request y outbox quedan en handlers/rutas, no como texto visible.

## Responsive, zoom y accesibilidad

La evidencia estructural cubre breakpoints compartidos 1023/639 px y reglas específicas 1199/900/820/720/520 px. Hay `min-width: 0` en grids, overflow local en tabs/semana, safe area en navegación y barras móviles, y modales con altura máxima y cuerpo desplazable. Conversaciones pasa de tres columnas a panel contextual y después a una vista operable. `prefers-reduced-motion` está definido.

Esto permite razonar sobre 360, 390, 768, 1024, 1280 y 1440 px, pero no sustituye una inspección visual. Tampoco se pudo comprobar zoom 125/150/200/400 %, reflow real, clipping, contraste renderizado ni lector de pantalla.

La estructura conserva un `h1`, skip link, landmarks, botones nativos, labels, foco visible, busy por bloque, touch targets compartidos y live regions acotados. Drawer, panel contextual y modales tienen teclado y retorno de foco. Pendiente: recorrido completo con Tab/Shift+Tab, NVDA o VoiceOver y zoom real.

## Seguridad frontend

Las peticiones pasan por `secureRequestOptions`; 401 y 403 cierran el contenido autenticado. Las rutas incluyen el slug y el backend resuelve de nuevo membresía y negocio. `escapeHtml` protege interpolaciones de datos; URLs públicas, OAuth y WhatsApp usan validadores de protocolo/destino; ventanas externas eliminan `opener` y los enlaces estáticos usan `noopener noreferrer`.

No hay rutas `/api/owner`, acciones Owner ni secretos en el HTML. La finalización de Meta consume IDs técnicos exclusivamente como payload. El filtro de errores rechaza mensajes largos, códigos, trazas, excepciones, payloads, SQL y tokens. También se retiraron cuerpo y URL del diagnóstico de media en consola.

## Rendimiento

No se hizo una optimización general. Los fingerprints evitan repintados de listas sin cambios; versiones impiden commits de respuestas viejas; los listeners estructurales se instalan una vez en `DOMContentLoaded`; búsquedas se desaceleran 350 ms; polling se pausa/reprograma por visibilidad y usa backoff. No se encontraron intervalos acumulativos ni un listener añadido al cambiar de sección.

Las listas siguen renderizadas con plantillas completas, una decisión aceptable con el volumen actual y la restauración de estado existente. Virtualización, fragmentación del archivo y medición de tiempos quedan como deuda futura, no como defectos de este sprint.

## Defectos confirmados y correcciones

| Defecto | Riesgo | Corrección |
| --- | --- | --- |
| `aria-current` dependía del observer del shell | Estado transitorio incoherente | Actualización síncrona en `showAdminSection` |
| Hash inválido permanecía en URL tras caer a Resumen | Deep link engañoso | Normalización a `#summary` |
| Tres regiones repintadas por polling tenían `aria-live` | Anuncios repetitivos | Retirada de live en sync, contador y reservas |
| Modal de bloqueo mostraba teléfono e ID de reserva | Exposición innecesaria | Se conservan nombre, servicio, estado y fecha |
| Conversaciones, notas, outbox y estados podían propagar detalles backend | Mensajes técnicos o secretos | Uso uniforme del filtro seguro |
| Log de media incluía URL y body | Datos innecesarios en consola | Solo acción y status HTTP |
| Cachebuster de `admin.js` era anterior a los últimos cambios | Cliente con JS obsoleto | Versión `20260805-1` |

## Pruebas

La nueva suite `backend/tests/test_admin_cross_section_qa.py` fija navegación principal/secundaria, enlaces contextuales, IDs y DOM, dirty state, polling, versiones, contexto de negocio, modales, accesibilidad, responsive, secretos, acciones Owner, métricas, namespaces API e integración entre secciones.

Se ejecutan además las suites focales de shell, polling, Dashboard, Agenda, Conversaciones, Configuración, Canales y Crecimiento, `ruff check backend/tests`, `git diff --check` y la suite completa. Los resultados finales se registran en el cierre del sprint; una prueba estática superada no se usa como sustituto de la sesión autenticada pendiente.

Resultados de esta revisión:

- suites focales: 96 pruebas y 12 subtests superados;
- prueba transversal nueva: 17 pruebas superadas, incluidas en el total focal;
- `ruff check backend/tests`: sin incidencias;
- suite completa: 473 pruebas y 53 subtests superados, 26 omitidos;
- warnings: 8197 avisos preexistentes, principalmente deprecaciones de fecha/hora y SQLAlchemy; no se ocultaron ni se trataron fuera de alcance.

## Capturas y validaciones pendientes

No se creó `docs/ux/screenshots/5F0/` porque no existía una sesión reproducible. La base local tenía cero usuarios y, además, estaba por detrás del esquema actual; no se ejecutaron migraciones ni se añadieron datos. Docker estaba disponible como CLI pero sin daemon, y no había servidor local activo. Edge estaba instalado, pero sin una aplicación autenticable no era posible capturar estados reales.

Pendiente en un entorno de desarrollo o staging controlado:

1. los 14 encuadres solicitados entre 360 × 800 y 1440 × 900;
2. cambio entre dos negocios autorizados, incluyendo respuestas lentas;
3. todos los estados vacíos, errores parciales y mutaciones críticas;
4. teclado completo, retorno de foco y ausencia de doble modal;
5. zoom 125/150/200/400 %, contraste y lector de pantalla;
6. inspección de red/DOM durante polling y cambio de tenant.

## Deuda y recomendación para 5C.1

La deuda inmediata no es una nueva función: es la validación dinámica pendiente. También conviene, en un sprint posterior, dividir `admin.js`, medir listas largas y definir un harness E2E autenticado con dos tenants de desarrollo.

Recomendación: **no iniciar todavía 5C.1 / Dashboard Owner como continuación automática**. Primero debe ejecutarse el recorrido autenticado y visual pendiente en un entorno controlado. Si no aparecen defectos bloqueantes, la base del Business Admin queda suficientemente estable para empezar 5C.1 sin reabrir este rediseño.
