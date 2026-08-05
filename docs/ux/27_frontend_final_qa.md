# QA transversal final de frontends — Sprint 5F.1

Fecha de corte: 5 de agosto de 2026. Rama: `main`. Base inicial: `1ee5b2e`.

## Alcance y estado inicial

La revisión comenzó con el árbol limpio, sin diff pendiente y con 5E.1 presente como `feat(public): rediseñar landing y experiencia de reserva`. Se inspeccionaron `autonogrow-owner`, `autonogrow-admin`, `autonogrow-landing`, `autonogrow-customer`, `autonogrow-shared`, las páginas legales, `backend/tests` y `docs/ux`.

Este sprint no cambia endpoints, payloads, modelos, migraciones, roles, permisos, aislamiento, disponibilidad, reservas ni onboarding. No incorpora capacidades comerciales ni frameworks. Las correcciones son frontend, pruebas y documentación.

## Inventario de superficies y riesgos

| Superficie | Ruta real | Usuario | Acción principal | Riesgo crítico revisado |
| --- | --- | --- | --- | --- |
| Owner dashboard | `autonogrow-owner/index.html#overview` | Owner | priorizar decisiones | fuentes parciales presentadas como correctas |
| Owner negocios | `#businesses` | Owner | abrir contexto de negocio | negocio equivocado |
| Owner onboarding | `#new-business` | Owner | continuar alta | progreso local o wizard duplicado |
| Owner aprobaciones | `#new-business`, vista Aprobaciones | Owner | revisar candidatura | aprobación sin consecuencia clara |
| Owner integraciones | `#integrations` | Owner | diagnosticar/reconectar | confundir salud, aprobación y capacidad |
| Owner incidencias | `#incidents` | Owner | reconocer/resolver | estado crudo o acción doble |
| Owner operaciones | `#operations` | Owner | revisar jobs y colas | IDs o errores técnicos visibles |
| Owner auditoría | `#audit` | Owner | filtrar actividad | datos fuera de contexto |
| Admin dashboard | `autonogrow-admin/index.html?b={slug}#summary` | Admin/Staff | atender agenda y mensajes | tenant o métrica inventada |
| Admin agenda | `#bookings` | Admin/Staff | gestionar reserva | mutación optimista o conflicto |
| Admin clientes | `#conversations`, panel cliente | Admin/Staff | consultar contexto | datos privados o N+1 |
| Admin conversaciones | `#conversations` | Admin/Staff | abrir hilo y responder | listeners inline, duplicados o estado obsoleto |
| Admin configuración | `#configuration` y categorías hijas | Admin | guardar sección | dirty state o etiquetas ambiguas |
| Admin canales | `#channels`, `#channel-instagram`, `#channel-whatsapp` | Admin | conectar/revisar | confundir canal con enlace público |
| Admin automatizaciones | `#messages` | Admin | configurar respuestas | activación sin canal |
| Admin reseñas | `#reviews` | Admin | preparar solicitud | afirmar envío no realizado |
| Admin crecimiento | `#growth` | Admin | revisar informe | porcentajes o impacto inventados |
| Landing pública | `autonogrow-landing/index.html?b={slug}` | Público | conocer negocio | tenant implícito |
| Reserva pública | `?b={slug}#booking` | Público | enviar solicitud | CTA prematuro o servicio no verificado |
| Resultado de reserva | paso Resultado en `#booking` | Público | consultar siguiente paso | mostrar `confirmed` falsamente o indexar |
| Mis citas | `autonogrow-customer/index.html` | Cliente | consultar citas propias | sesión caducada como vacío |
| Detalle de cita | diálogo de Mis citas | Cliente | consultar negocio/contacto | ID en URL o diálogo inaccesible |
| Login | compuerta integrada de Owner/Admin/Customer | Según rol | autenticarse | flash protegido, loop o mensaje revelador |
| Logout | botones de cada panel | Autenticado | cerrar sesión | estado previo persistente |
| Privacidad | `privacy/index.html` | Público | consultar tratamiento | enlace o reflow roto |
| Eliminación de datos | `data-deletion/index.html` | Público | consultar procedimiento | instrucción inaccesible |
| Errores HTTP | estados locales de cada superficie | Todos | comprender y reintentar | mezclar 401, 403, 404, 409, 422, 429 y 5xx |

No se inventaron rutas. Login y detalle son estados dentro de sus documentos, no páginas nuevas.

## Responsive y reflow

La evidencia es estructural y automatizada, no visual autenticada.

| Viewport | Comportamiento comprobado en código | Validación visual |
| --- | --- | --- |
| 360 × 800 | columnas únicas, grids `minmax(0, 1fr)`, controles de 16 px, barra inferior con safe area | pendiente |
| 390 × 844 | calendario 3 columnas y slots 2 columnas; tarjetas permiten wrapping | pendiente |
| 412 × 915 | reglas móviles de 639/680/767 px; acciones apilables | pendiente |
| 768 × 1024 | drawer compartido y grids de una/dos columnas | pendiente |
| 820 × 1180 | transición de conversaciones y formularios sin columnas comprimidas | pendiente |
| 1024 × 768 | shell de escritorio desde 1024 px; contenido con `min-width: 0` | pendiente |
| 1280 × 800 | conversaciones en modo de tres paneles y anchos máximos | pendiente |
| 1366 × 768 | densidad de paneles limitada por contenedores | pendiente |
| 1440 × 900 | anchos máximos de Owner, Admin y Landing | pendiente |
| 1920 × 1080 | contenido no se estira sin límite | pendiente |

Se comprobó la relación entre DOM y CSS: drawer, topbar, navegación móvil, conversaciones, agenda semanal, calendario público, slots, formularios, diálogos y barras sticky tienen contenedores reducibles u overflow local. Los textos largos importantes usan `overflow-wrap`; el título móvil del shell deja de truncarse con ellipsis. Los inputs Owner/Admin, Landing y Customer quedan en 16 px en móvil.

Las barras inferiores y el CTA público usan `env(safe-area-inset-bottom)`; la cabecera pública incorpora `safe-area-inset-top`. Los diálogos usan `100dvh` y scroll interno. Reagendar dejó de depender de `vh` en sus alturas máximas.

## Zoom

La estructura permite reflow a 125, 150, 200 y 400 % mediante grids reducibles, wrapping, menús drawer, controles apilables y ausencia de alturas rígidas en contenido textual. El título del shell ya no se corta al estrecharse. Quedan pendientes la observación renderizada a cada zoom, el teclado virtual y el cálculo real de `scrollWidth`.

## Navegación, shell y contexto

Se preservan `?b=slug`, hashes, deep links de reserva y las rutas internas existentes. Owner mantiene dashboard → negocio → onboarding/usuarios/marca/canales, aprobaciones → candidatura, integraciones → negocio y operaciones → incidencia. Admin mantiene dashboard → Agenda/Conversaciones, Agenda → reserva, Conversaciones → hilo/cliente, Configuración → categoría, Canales → conexión y Crecimiento → acción real. Landing conserva anclas y Resultado → Mis citas; Customer conserva detalle, mapa y contacto.

El shell compartido mantiene skip link, drawer, backdrop, `inert`, Escape, retorno de foco, cierre al navegar y sincronización por breakpoint. No se añadió polling ni un segundo listener por render. Los recursos modificados usan cachebuster `v=5f1` y los scripts conservan orden GSI → auth → shell → módulo.

## Semántica, foco y teclado

Los IDs estáticos son únicos; las referencias ARIA estáticas resuelven y los títulos de panel Owner se crean junto con su contenido dinámico. Cada estado renderizado tiene un solo `h1`; los documentos con compuerta auth/error mantienen dos `h1` mutuamente excluyentes. Los fieldsets tienen legend, los botones estáticos y generados declaran `type`, no hay `div onclick`, `span onclick`, `href="#"` ni handlers inline.

Drawer, galería, detalle de cita y cuatro diálogos operativos conservan Escape, focus trap donde corresponde, foco inicial y retorno al activador. Los errores largos siguen teniendo resumen/foco. Calendario y slots son botones con selección textual y `aria-pressed`; no dependen solo del color.

## Formularios

Los controles estáticos tienen label nativo o nombre accesible. Se corrigieron los cuatro campos hexadecimales del Admin y los equivalentes Owner para que el segundo control del par tenga un nombre inequívoco. El texto alternativo de una nueva foto y los controles legacy de usuario Owner ya no dependen del placeholder. Los obligatorios estáticos conservan asterisco, límites, tipos y autocomplete existentes.

No cambiaron validaciones backend. Continúan las guardas de doble envío, dirty state, conservación tras fallo, snapshots y limpieza tras éxito ya cubiertas por las suites focales.

## Diálogos y confirmaciones

Se inventariaron reagenda, bloqueo de eliminación de personal, acción crítica Owner, salida con cambios, galería y detalle de cita. Tienen `role=dialog`, `aria-modal`, título y descripción cuando procede. Los paneles caben en `100dvh`, permiten scroll interno y bloquean el fondo. Las etiquetas distinguen Cancelar, Confirmar, Cerrar, Salir sin guardar y Guardar y salir.

## Carga, vacíos, errores y feedback

Owner y Admin mantienen `aria-busy` por fuente y reintentos parciales. Landing distingue comprobación, catálogo vacío, fallo total y resultado parcial; Customer distingue sesión caducada, próximas vacías e historial vacío. La carga no se interpreta como vacío y una fuente secundaria no sustituye datos válidos por un spinner global.

Los mensajes siguen separando sesión, permisos, recurso no disponible, conflicto, validación, límite, fallo temporal y conexión. Toasts, banners, regiones live y feedback inline mantienen su uso anterior; los fallos críticos no dependen de un toast efímero.

## Estados, fechas y números

Se eliminaron fallbacks que imprimían códigos desconocidos en Owner, onboarding, reservas, mensajes, canal e intención. Salud, token, suscripción y activo de integraciones Owner se traducen y un valor desconocido cae en “Estado no disponible”. Las clases de salud usan tonos conocidos, no el código recibido.

Las funciones corregidas no muestran `Invalid Date` ni devuelven el timestamp inválido: fechas de baja, conversación, onboarding, salud y periodos usan texto seguro. Agenda y reserva conservan sus helpers de fecha civil y zona del negocio. Precios ausentes siguen separados de cero; duraciones, créditos, porcentajes y contadores no cambian su fuente.

## Tablas, listas, tarjetas y calendarios

No hay tablas estáticas usadas como layout. Agenda semanal, pestañas, filtros y listas extensas usan overflow local explícito. Las tarjetas conservan contexto, estado y acción sin mostrar IDs como texto. La reserva pública continúa verificando servicios por personal compatible, versiona fechas/slots y bloquea conflicto o selección obsoleta antes del POST.

## Seguridad frontend y contratos DOM

No hay `eval`, `new Function`, `document.write`, `javascript:`, `data:text/html`, `console.log`, `console.debug` ni `localStorage`. `sessionStorage` queda limitado a `adminMediaPending` y `ownerMediaPending`, con slug y tipo de medio; no persiste datos personales ni credenciales. Los tokens Owner siguen siendo inputs password y payload de una operación autorizada, nunca HTML ni almacenamiento.

Landing y Customer no usan `innerHTML`; Admin y Owner conservan renderizado heredado protegido por helpers de escape. Los enlaces `_blank` estáticos y generados llevan `noopener`; las ventanas WhatsApp eliminan `opener`. El log compartido de autenticación ya no incluye body ni objeto de error, solo status.

Las referencias literales `getElementById`/`byId`/`q` resuelven contra HTML o creación dinámica deliberada. No hay IDs, scripts ni funciones duplicados dentro de cada módulo. El Admin reemplaza todos los handlers inline por un dispatcher único y la prueba cruza cada `data-admin-action` con una rama implementada.

## Rendimiento y ciclo de vida

No se añadió polling. Admin conserva single-flight, backoff, fingerprints y versiones; Owner, Landing y Customer mantienen descarte de respuestas obsoletas. La verificación pública conserva caché en memoria con concurrencia limitada. La delegación Admin reduce listeners generados y se registra una sola vez en `DOMContentLoaded`.

Las imágenes públicas conservan lazy loading y dimensiones. No se introdujo virtualización ni optimización especulativa.

## Contraste, tipografía, movimiento, forced colors e impresión

El foco visible no depende del color de marca. Landing calcula texto sobre primario y usa fallbacks. Se añadieron bordes explícitos para selección, controles y badges en forced colors de Landing/Customer; Owner/Admin heredan la regla compartida. Todas las superficies interactivas tienen reduced motion. Landing y Customer ocultan elementos fijos y diálogos al imprimir para que no tapen contenido.

La comprobación de contraste renderizado, Windows High Contrast real, lector de pantalla y fuentes cargadas queda pendiente de navegador operativo.

## Autenticación

Owner, Admin y Customer parten ocultos hasta `getMe`; el documento actual conserva slug, hash y destino durante el login integrado. Logout usa CSRF y vuelve al estado anónimo. 401 y 403 no se convierten en contenido vacío. No se añadieron selectores de rol ni accesos administrativos anónimos.

## Revisión por producto

- **Owner:** contexto, readiness, onboarding, candidaturas, integraciones, incidencias, jobs, diálogos y traducciones revisados. Se corrigieron estados crudos, fechas y nombres accesibles.
- **Business Admin:** dashboard, agenda, clientes, conversaciones, configuración, canales, automatizaciones, reseñas y crecimiento revisados. Se eliminaron handlers inline, botones sin tipo y etiquetas ambiguas sin cambiar acciones.
- **Landing:** slug explícito, servicios verificados, CTA, staff, calendario, slots, POST, conflicto, resultado, noindex seguro, responsive, forced colors e impresión revisados.
- **Customer:** compuerta auth, próximas, historial, detalle, mapa, contacto, vacíos, sesión, diálogo, forced colors, footer legal e impresión revisados.

## Defectos corregidos

| Defecto confirmado | Riesgo | Corrección |
| --- | --- | --- |
| handlers `onclick`/`onchange` en Admin estático y generado | CSP, duplicación y contratos difíciles de probar | dispatcher único con `data-admin-action`/`data-admin-change` |
| dos botones de galería generados sin `type` | submit accidental | `type="button"` explícito |
| inputs hex y recursos Owner con nombre ambiguo | lector de pantalla/placeholder como label | nombres accesibles explícitos |
| estados desconocidos impresos en crudo | jerga interna/exposición | fallbacks seguros y traducciones de salud |
| fechas inválidas devueltas como texto recibido | valor técnico o inconsistente | fecha no disponible/guion seguro |
| título del shell truncado en móvil | pérdida de contexto a zoom | wrapping con `overflow-wrap` |
| inputs Admin sin garantía explícita de 16 px móvil | zoom automático en iOS | regla compartida de 1 rem |
| modal de reagenda dependía de `vh` | teclado y barras del navegador | `dvh` |
| Landing/Customer sin forced colors propio | selección dependiente del fondo | bordes y outline en forced colors |
| log auth incluía body/error | diagnóstico excesivo | solo status numérico |
| assets modificados con versiones antiguas | clientes con CSS/JS obsoleto | cachebuster `v=5f1` |
| Customer sin enlaces legales persistentes | salida legal poco clara | footer de Privacidad/Eliminación |

## Pruebas automatizadas

`backend/tests/test_frontend_final_qa.py` contiene 16 pruebas transversales sobre inventario, assets, orden, cachebusters, IDs, ARIA, labels, botones, handlers, dispatcher, DOM, diálogos, estados, fechas, seguridad, enlaces, responsive, zoom estructural, reduced motion, forced colors, impresión, auth, duplicación y namespaces API.

Las suites existentes de Admin se adaptaron para comprobar el nuevo contrato delegado sin relajar la garantía de navegación interna.

Resultados finales con el entorno virtual del repositorio:

- `pytest backend/tests/test_frontend_final_qa.py -q`: 16 pruebas superadas.
- Subconjunto transversal de shell, Owner, Admin, Landing/reserva, onboarding, servicios, staff, conversaciones, canales, automatizaciones e aislamiento Instagram: 321 pruebas y 38 subpruebas superadas.
- `ruff check backend/tests`: sin incidencias.
- `git diff --check`: sin errores de whitespace; Git solo avisa de la conversión configurada LF/CRLF en el working copy.
- `pytest -q`: 628 pruebas y 53 subpruebas superadas, 26 omitidas; permanecen avisos de deprecación ya existentes.

## Navegador y capturas

Microsoft Edge está instalado, pero no hay backend escuchando en `127.0.0.1:8000`, no se detectó base local y no existe una sesión autenticada reproducible. Se intentó Edge headless sobre Privacidad y el estado público sin slug a 360, 390, 768 y 1440 px; el proceso terminó con `GPU process isn't usable` y no generó capturas.

No se modificaron datos, no se fabricaron estados y no se incluyen capturas. No se afirma validación visual, de red, consola, zoom, teclado o lector.

## Deuda y validación pendiente en piloto

1. Recorrer los diez viewports y zoom 100/125/150/200/400 % con backend y cuentas autorizadas.
2. Medir `scrollWidth`, overlays, teclado móvil y barras sticky con contenido real largo.
3. Probar Tab/Shift+Tab/Enter/Espacio/Escape, lector de pantalla y forced colors real.
4. Cambiar entre dos tenants autorizados con red lenta y comprobar ausencia de frame obsoleto.
5. Observar 401, 403, 404, 409, 422, 429, 5xx, timeout y offline reales sin alterar la base.
6. Validar flujos de Owner/Admin, reserva real y Customer con datos no sensibles.
7. Medir contraste renderizado y revisar impresión de informe/detalle/landing.
8. Evaluar en un sprint posterior la retirada del markup legacy Owner que hoy queda sustituido por el hub, sin mezclar esa refactorización con el QA final.

## Preparación para piloto

El frontend queda como **candidato estructural para validación piloto**: contratos y regresiones automatizadas están cubiertos y no hay cambios backend funcionales. La aprobación visual y operativa final requiere completar la lista anterior en un entorno autenticado reproducible. No se inicia 5G.1 desde este sprint.
