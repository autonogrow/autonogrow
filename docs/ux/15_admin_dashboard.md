# 15 — Dashboard operativo del Business Admin

## Alcance

Sprint 5B.1 rediseña únicamente `Inicio`. El objetivo es responder con rapidez cuántas citas hay hoy, qué reservas y conversaciones requieren respuesta, cuál es la próxima cita y si existe un bloqueo operativo. Agenda, Conversaciones y configuración conservan su estructura y lógica anteriores.

No se añadieron endpoints, modelos, permisos, dependencias ni polling. El dashboard deriva sus datos de respuestas que el panel ya cargaba.

## Estructura final

```text
Cabecera: saludo, fecha, resumen y acceso a Agenda
├── Citas de hoy
├── Por confirmar
├── Mensajes sin responder
└── Estado del negocio

Contenido
├── Necesita tu atención
├── Próxima cita
├── Agenda de hoy (máximo 5)
├── Mensajes recientes (máximo 4)
└── Actividad de los últimos 7 días
```

La tarjeta heredada de Crecimiento permanece al final para no ampliar este sprint ni romper su lógica. Los IDs de las métricas anteriores permanecen en un contenedor oculto de compatibilidad mientras sus consumidores JavaScript sigan activos.

No se muestra `Nueva reserva`: el Admin no tenía un flujo compatible para crearla. La acción principal abre la vista existente `Reservas → Hoy`.

## Fuentes de datos reutilizadas

| Fuente existente | Endpoint | Uso en Inicio |
|---|---|---|
| Negocio Admin | `GET /api/admin/businesses/{slug}/settings` | nombre, publicación y contexto del negocio |
| Panel de personal | `GET /api/admin/businesses/{slug}/panel` | negocio visible para `business_staff` |
| Reservas | `GET /api/admin/businesses/{slug}/bookings` | indicadores, agenda, próxima cita, pendientes y actividad |
| Conversaciones | `GET /api/admin/businesses/{slug}/conversations?limit=100&offset=0` | pendientes y previews recientes |
| Servicios | `GET /api/admin/businesses/{slug}/services` | recomendación si no existe servicio activo |
| Disponibilidad | `GET /api/admin/{slug}/availability-settings` | recomendación si no existe ningún tramo semanal |
| Incorporación de canales | `GET /api/admin/businesses/{slug}/channel-onboarding` | contexto de canales autorizado para Admin |
| Salud de canales | `GET /api/admin/businesses/{slug}/channels/health` | alerta segura de reconexión o revisión |

La actividad reciente cuenta reservas recibidas por `created_at`, citas completadas y citas canceladas/rechazadas dentro de los últimos siete días. No calcula porcentajes, ingresos ni comparativas.

Las conversaciones del dashboard conservan la última respuesta sin filtros. Los filtros de la bandeja no cambian las métricas de Inicio y tampoco provocan una segunda solicitud. Mientras un filtro permanece activo, Inicio conserva el último snapshot global conocido hasta que vuelva a cargarse la lista sin filtros.

## JavaScript

Las funciones nuevas son pequeñas y se apoyan en el estado existente:

- `renderDashboard()` coordina los bloques sin realizar red.
- `renderDashboardHeader()` y `renderDashboardMetrics()` presentan el resumen.
- `renderTodayBookings()` y `renderNextBooking()` derivan y ordenan reservas.
- `renderAttentionItems()` construye tareas solo a partir de condiciones conocidas.
- `renderMessageSummary()` limita las previews y escapa sus textos.
- `renderRecentActivity()` calcula los últimos siete días.
- `renderDashboardBlockError()` y `renderDashboardEmptyState()` unifican feedback.
- `setupDashboardInteractions()` registra una única delegación de eventos.

`loadBookings()`, `loadConversations()`, `loadAdminServices()`, `loadAvailabilitySettings()` y `loadBusinessChannelOnboarding()` notifican carga, éxito o error. No existe `loadDashboardData()` paralelo y no se duplican llamadas.

El polling conserva las tareas y frecuencias anteriores:

- hilo de conversación;
- lista de conversaciones;
- operaciones, que agrupa reservas y outbox.

## Estados

### Carga

Indicadores y bloques reservan espacio mediante `ag-skeleton`. El texto accesible queda visualmente oculto y los contenedores usan `aria-busy`.

### Vacío

- Agenda: “No tienes citas para hoy”.
- Próxima cita: “No hay una próxima cita”.
- Atención: “Todo está al día”.
- Mensajes: “No hay mensajes pendientes”.
- Actividad: “Aún no hay actividad reciente”.

Cada vacío ofrece una acción cuando existe un destino real.

### Error parcial

Reservas, conversaciones, servicios, horarios y canales mantienen estado independiente. Un fallo muestra texto seguro y `Reintentar`; los demás bloques continúan visibles. El polling con datos previos conserva el último contenido y señala el error temporal en el indicador de sincronización existente.

### Traducción de estados

| Interno | Dashboard |
|---|---|
| `requested` | Por confirmar |
| `pending` | Pendiente |
| `confirmed` | Confirmada |
| `completed` | Completada |
| `cancelled` | Cancelada |
| `rejected` | Rechazada |
| `no_show` | No presentado |

## Responsive

- **≥1024 px:** cuatro indicadores; Agenda y Actividad en columna principal, Atención/Próxima cita/Mensajes en columna secundaria.
- **640–1023 px:** indicadores 2×2; Atención y Próxima cita comparten primera fila; Agenda ocupa todo el ancho.
- **<640 px:** orden DOM y visual Cabecera → Indicadores → Atención → Próxima cita → Agenda → Mensajes → Actividad. Todas las tarjetas forman una columna, salvo los cuatro indicadores 2×2. Las acciones pasan a ancho completo y no se usan tablas.

La barra inferior del shell conserva el espacio reservado mediante `safe-area-inset-bottom`.

## Accesibilidad

- Un único `h1` para el nombre del negocio y jerarquía `h2`/`h3`/`h4` dentro de Inicio.
- Regiones nombradas con `aria-labelledby` o `aria-label`.
- Actualizaciones moderadas mediante una única región `aria-live=polite`.
- Errores parciales con `role=alert` y controles reales.
- Skeletons decorativos ocultos y texto de carga disponible.
- Estado expresado mediante texto, forma y color.
- Orden DOM equivalente al orden móvil.
- Navegación por botones existentes y foco devuelto al contenido principal.

## Seguridad

El `business_slug` sigue procediendo de la URL y todas las solicitudes pasan por el wrapper autenticado existente. La autorización continúa en backend.

Los nombres de clientes, servicios y profesionales, así como contacto, canal y extracto del mensaje, pasan por `escapeHtml()` antes de entrar en templates. Los extractos se normalizan y limitan a 88 caracteres. Los IDs usados en acciones deben convertirse en enteros positivos. Inicio no renderiza URLs externas, tokens, scopes, WABA, IDs de proveedor, payloads ni errores técnicos.

## Pruebas

`backend/tests/test_admin_dashboard.py` comprueba bloques, cuatro métricas, IDs únicos, contratos heredados, navegación, traducciones, vacíos, errores parciales, escaping, accesibilidad, CSS responsive y ausencia de `fetch()` dentro de la capa de render del dashboard.

Comandos previstos:

```powershell
.venv\Scripts\python.exe -m pytest backend\tests\test_shared_app_shell.py -q
.venv\Scripts\python.exe -m pytest backend\tests\test_admin_polling.py -q
.venv\Scripts\python.exe -m pytest backend\tests\test_admin_dashboard.py -q
.venv\Scripts\ruff.exe check backend\tests
git diff --check
```

## Validación visual pendiente

El entorno no dispone actualmente de Chrome, Edge, Firefox, Chromium, Playwright ni Selenium. No se generaron capturas ni se afirma validación visual.

Con una sesión demo autenticada y el repositorio servido mediante el procedimiento local habitual:

```powershell
npx playwright screenshot --viewport-size="1440,900" "http://127.0.0.1:8000/autonogrow-admin/index.html?b=demo" docs/ux/screenshots/5B1/admin-1440.png
npx playwright screenshot --viewport-size="1024,768" "http://127.0.0.1:8000/autonogrow-admin/index.html?b=demo" docs/ux/screenshots/5B1/admin-1024.png
npx playwright screenshot --viewport-size="768,1024" "http://127.0.0.1:8000/autonogrow-admin/index.html?b=demo" docs/ux/screenshots/5B1/admin-768.png
npx playwright screenshot --viewport-size="390,844" "http://127.0.0.1:8000/autonogrow-admin/index.html?b=demo" docs/ux/screenshots/5B1/admin-390.png
npx playwright screenshot --viewport-size="360,800" "http://127.0.0.1:8000/autonogrow-admin/index.html?b=demo" docs/ux/screenshots/5B1/admin-360.png
```

Un script visual válido debe reutilizar `storageState`; no debe desactivar autenticación. Debe comprobar con citas/tareas, vacío y error parcial: overflow global, truncado de nombres, drawer, barra inferior, foco, zoom y contenido inferior.

## Deuda deliberada

- Capturas y regresión visual autenticada.
- Pruebas en navegador del polling y los botones de reintento.
- Focus trap de modales heredados, fuera del alcance de Inicio.
- Endpoint agregado futuro solo si el volumen de datos hace ineficiente cargar listas completas; este sprint no lo inventa.
- Rediseño de Agenda y Conversaciones en 5B.2/5B.3.
