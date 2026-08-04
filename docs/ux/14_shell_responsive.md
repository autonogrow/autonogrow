# 14 — Shell responsive

## Arquitectura aplicada

Admin y Owner usan el mismo shell con sus menús existentes:

```text
main.ag-shell[data-ag-shell]
├── backdrop
├── aside.ag-shell__sidebar
│   ├── marca
│   ├── slot de navegación
│   └── contexto inferior
└── div.ag-shell__main
    ├── header.ag-topbar
    └── div.ag-shell__content
        └── div.ag-content-container
```

`app-shell.js` mueve el nodo `[data-ag-shell-nav]` existente al slot del sidebar antes de que `admin.js`/`owner.js` registren sus listeners. No clona botones ni `data-*`. Si el módulo no carga, el menú sigue en el documento como fallback.

## Comportamiento por anchura

### Desktop — 1024 px o más

- Sidebar oscura de 272 px, sticky y con scroll propio.
- Icono, label e indicador geométrico del elemento activo.
- Topbar sticky compacta con contexto, sincronización/acciones y usuario.
- Contenido fluido con máximo 1280 px.
- Las secciones, panels, hashes y botones existentes no cambian.

### Tablet — 640 a 1023 px

- Sidebar se convierte en drawer fuera de pantalla.
- Botón de menú con `aria-controls` y `aria-expanded` en topbar.
- Backdrop y cierre explícito.
- Escape y click exterior cierran; el scroll de body se bloquea.
- El contenido principal se marca `inert` mientras el drawer está abierto cuando el navegador lo soporta.
- Resúmenes pasan a dos columnas; el resto conserva breakpoints legacy más overrides seguros.

### Móvil — menos de 640 px

- Mismo drawer para el menú completo.
- Admin añade barra inferior de cuatro destinos: Inicio → `summary`, Agenda → `bookings`, Mensajes → `conversations`, Más → drawer.
- Los botones móviles delegan el click al botón `data-section` original; `showAdminSection()` conserva hash, visibilidad y permisos.
- “Más” queda activo para growth, messages/outbox, servicios, equipo, horarios, canales, negocio y reseñas.
- Barra con 44 px mínimos, label visible y `safe-area-inset-bottom`; el contenido reserva espacio inferior.
- Owner mantiene drawer y no adopta barra inferior por su naturaleza operativa.
- Grids de canales, formularios, resúmenes e incidencias se fuerzan a una columna; corrige la cuadrícula Owner de dos columnas observada a 360/390 px.

## Navegación y accesibilidad

- Enlaces “Saltar al contenido” apuntan a contenedores enfocables.
- Aside y nav tienen nombres accesibles.
- Los disparadores sincronizan `aria-expanded`; el menú activo usa `aria-current=page`.
- Un `MutationObserver` observa únicamente cambios de clase del menú para acompañar la navegación existente.
- Cerrar el drawer devuelve foco al disparador; elegir destino lleva foco al contenido.
- Escape solo interviene cuando el drawer está abierto.
- Focus ring de 3 px y `prefers-reduced-motion` compartidos.
- SVG decorativos están ocultos; botones de icono tienen label.

## Contratos preservados

Admin mantiene los once `data-section`, once `data-admin-section`, hashes, `#admin-app`, `#business-name`, sincronización, reservas, conversaciones y ambos modales. Owner mantiene cinco `data-tab`, cinco `data-panel`, `#business-list`, onboarding, incidencias, queues y operaciones. No se modificó ninguna llamada API, método HTTP, autenticación, permiso, slug, `business_id` ni flujo Meta.

## Muestra de integración

Admin: shell/sidebar/topbar, navegación móvil, botones de topbar, tarjetas de resumen, formulario de negocio, badge de estado, alerta de canales y ambos modales.

Owner: shell/sidebar/topbar, tarjeta de métrica, filtro de incidencias, badges generados, alerta operativa y acción peligrosa de mantenimiento. Las tarjetas extensas y el onboarding no se rediseñan.

## Validación responsive

Anchuras objetivo: 360×800, 390×844, 768×1024, 1024×768 y 1440×900.

No había Chrome, Edge, Firefox, Chromium, Playwright ni Selenium. No se generaron capturas ni se afirma una validación visual. Se realizaron validaciones estáticas de archivos, refs, IDs, navegación, clases, atributos accesibles y JS por inspección; la sintaxis automatizada de JavaScript no pudo ejecutarse porque Node, Deno, Bun y QuickJS tampoco estaban disponibles.

Comandos reproducibles cuando exista navegador:

```powershell
# Servir el repositorio con el procedimiento local habitual y autenticar datos demo.
npx playwright screenshot --viewport-size="1440,900" "http://127.0.0.1:8000/autonogrow-admin/index.html?b=demo" docs/ux/screenshots/5A2/admin-1440.png
npx playwright screenshot --viewport-size="768,1024" "http://127.0.0.1:8000/autonogrow-admin/index.html?b=demo" docs/ux/screenshots/5A2/admin-768.png
npx playwright screenshot --viewport-size="390,844" "http://127.0.0.1:8000/autonogrow-admin/index.html?b=demo" docs/ux/screenshots/5A2/admin-390.png
npx playwright screenshot --viewport-size="1440,900" "http://127.0.0.1:8000/autonogrow-owner/index.html" docs/ux/screenshots/5A2/owner-1440.png
npx playwright screenshot --viewport-size="768,1024" "http://127.0.0.1:8000/autonogrow-owner/index.html" docs/ux/screenshots/5A2/owner-768.png
```

El comando genérico no resuelve autenticación por sí mismo. Para capturas válidas debe usarse un script Playwright temporal con storage state de una cuenta demo sin datos sensibles; no se debe desactivar autenticación.

## Checklist visual pendiente

1. Ausencia de `documentElement.scrollWidth > innerWidth` en las cinco anchuras.
2. Drawer, backdrop, Escape, foco, scroll lock y resize abierto/cerrado.
3. Sidebar con textos largos y viewport de poca altura.
4. Topbar Admin/Owner con nombre/email largo y errores de sincronización.
5. Barra inferior sin tapar última acción, modal ni teclado virtual.
6. Modal de reagenda/personal con contenido largo.
7. Contraste y zoom 200/400 %, forced colors, teclado y lector.

## Deuda deliberada

- Focus trap/retorno de foco de modales, que pertenece al futuro gestor de diálogo.
- Vista responsive profunda de agenda/conversaciones/onboarding.
- Deep links Owner y nueva arquitectura de información.
- Capturas y regresión visual autenticada.
- Integración visual de Customer y Landing.

