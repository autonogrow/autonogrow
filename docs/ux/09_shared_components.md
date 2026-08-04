# 09 — Componentes compartidos, CSS y arquitectura JavaScript

## Estado de `autonogrow-shared`

La carpeta comparte autenticación (`auth.js`, `auth.css`) y páginas legales (`legal.css`). Es útil y pequeña, pero no existe un sistema de diseño compartido ni primitivas de interacción. Cada app redefine botones, grids, tarjetas, badges, feedback, navegación y tipografía.

La próxima capa compartida debe ser aditiva. No reemplazar `.btn` o `.button`: añadir una clase neutral a ambos y migrar consumidores gradualmente.

## Componentes repetidos

| Componente | Dónde/diferencias | Duplicación | Unificación propuesta | Riesgo |
|---|---|---|---|---|
| Botón | `.btn` Admin, `.button` Owner, estilos propios Landing/Customer | Alta | `.ag-button` con variantes primary/secondary/danger/quiet/size | selectores JS/inline y colores de tema |
| Tarjeta/panel | métricas, citas, negocios, integración, servicio | Alta | surface/card + slots de heading/body/actions | no forzar la misma densidad a landing y operaciones |
| Badge/estado | booking, health, state, automation | Alta | badge semántico neutral/success/warning/danger; texto obligatorio | un color no puede mapear estados de dominios distintos |
| Feedback | inline, empty, alert, console | Muy alta | feedback + status region + error summary | mutaciones asíncronas y foco |
| Form field | labels/inputs/selects/textarea | Alta | field, hint, error, group/fieldset | conservar IDs/names/data/body |
| Navegación | tabs Admin/Owner, quick-nav Landing | Media | shell nav y patrón mobile; no un único componente para anclas y tabs | semántica distinta |
| Modal/confirmación | dos Admin + nativos Owner | Alta | dialog manager accesible, confirmación destructiva | foco, funciones globales, motivo obligatorio |
| Estado vacío/carga | texto/card por cada lista | Alta | empty-state con título, ayuda, acción; skeleton/status opcional | no ocultar errores como vacío |
| Filtros | bookings/conversations/incidents/queues/outbox | Alta | filter bar responsive | query/body y auto-submit varían |
| Tarjeta de integración | Admin/Owner | Alta | resumen por capas + health action | roles muestran detalle diferente |
| Tarjeta de cita | Admin/Customer | Media | datos/estado base; acciones inyectadas por rol | no filtrar datos solo en UI |
| Topbar | cuatro apps | Media | marca, contexto, user menu, sync slot | landing pertenece al negocio, no a AutonoGrow |
| Loader/toast/paginación | no hay patrón consistente | Ausente | añadir cuando exista necesidad real; feedback persistente para errores | toast no debe ser única vía ni autoocultarse con acción |

## Cifras CSS aproximadas

Método: regex sobre fuentes, contando valores hex distintos, declaraciones de custom properties, expresiones `@media`, `!important` y estilos HTML inline. Los colores calculados, RGB/nombres y repetición semántica no se normalizaron; son indicadores, no una auditoría de uso.

| Archivo/app | Hex distintos | Variables declaradas | Media queries distintas | `!important` | Inline HTML |
|---|---:|---:|---:|---:|---:|
| Admin | 45 | 11 | 4 | 5 | 1 |
| Owner | 43 | 9 | 2 | 1 | 0 |
| Customer | 9 | 0 | 1 | 0 | 0 |
| Landing | 27 | 12 | 2 | 0 | 0 |
| Shared auth | 6 | 0 | 0 | 1 | 0 |
| Shared legal | 0 hex | — | 1 | 0 | 0 |
| Global deduplicado | **97** | **21 variables únicas** | **10 expresiones/bloques** | **7** | **1** |

Hay además estilos inline generados por JS (por ejemplo anchura de progressbars y selección de slots), que el recuento HTML no incluye. Las “reglas aparentemente duplicadas” no pueden reducirse a un número fiable sin parser y comparación de cascada; la inspección confirma familias repetidas de botones, cards, formularios, badges y selectores de seis temas. Se estima **más de 30 bloques/familias solapadas**, pendiente de Stylelint/CSS AST antes de borrar cualquier regla.

### Deuda visual

- Paletas y variables se redefinen por app; no hay tokens semánticos de surface/text/border/focus/status.
- Admin usa Arial/sistema; Owner mezcla Georgia y sistema; las fuentes objetivo Montserrat/Inter aún no forman una política transversal.
- Breakpoints no coordinados: 420, 520, 600, 640, 680, 720, 760, 820 y 900 px. El resultado son cliffs distintos a 768/820.
- Radios, sombras y densidad varían sin escala común.
- `z-index` de overlays llega a 999; falta una escala y documentación de capas.
- La clase genérica `.active` se usa en varios productos; hoy los CSS están separados, pero sería un riesgo al compartir hojas.
- No retirar `!important`, estilos inline ni selectores específicos sin medir cascada/DOM dinámico.

## Tokens propuestos

Identidad requerida: azul `#1E90FF`, coral `#FF6F61`, verde `#2ECC71`, negro `#1A1A1A`, blanco gris `#F5F5F5`; títulos Montserrat e interfaz Inter. Antes de aplicarlos, derivar pares accesibles para hover, texto sobre color, bordes y foco; los cinco valores no bastan como paleta semántica.

```text
autonogrow-shared/
├── tokens.css          color, type, space, radius, shadow, z, motion
├── primitives.css      button, field, badge, card, feedback, empty
├── shell.css           container, header, desktop/mobile navigation
├── dialog.js           foco, Escape, retorno y confirmación
├── api.js              respuesta JSON/error/abort; sobre AutonoGrowAuth
├── dom.js              escape/render helpers y delegación segura
└── a11y.js             live regions, focus helpers, reduced motion
```

## JavaScript actual

| Archivo | Líneas | Funciones aprox. | `fetch` | `innerHTML` | listeners | selectores/IDs aprox. |
|---|---:|---:|---:|---:|---:|---:|
| `admin.js` | 3.906 | 181 | 63 | 54 | 37 | 260 |
| `owner.js` | 1.138 | 67 | 32 | 31 | 29 | 80+ (más helper `byId`) |
| `script.js` Landing | 1.005 | 37 | 9 | 31 | 8 | 62 |
| `customer.js` | 68 | 7 | wrapper | 2 | 2 | 16 |
| `auth.js` | 95 | — | 2 directos | 1 | — | — |

Recuento mecánico; template strings y funciones flecha hacen la cifra aproximada.

### Hallazgos

1. Admin y Owner concentran estado global, API, validación, navegación y render. Esto dificulta prueba aislada y control de carreras.
2. `innerHTML` es extensivo. Existe `escapeHtml()` y se usa en muchas interpolaciones externas, una defensa positiva; cada nueva interpolación debe revisarse. URLs/atributos, mensajes backend y templates son puntos sensibles.
3. Hay handlers inline en Admin (`onclick`) y funciones globales. Impiden modularizar directamente sin exportar puentes compatibles.
4. Los errores no tienen un tipo común; a veces se parsea `detail`, otras se pierde status/body o se registra en consola.
5. Owner tiene carga N×negocios y acciones construidas dinámicamente en una función central.
6. Landing mezcla tema/contenido, disponibilidad, reserva, adjuntos y confirmación, pero sí protege cambios rápidos de servicio con versionado.
7. No se identificó uso de HTML externo sin escape que demuestre una XSS explotable en esta auditoría; el volumen de `innerHTML` mantiene un riesgo de regresión y requiere tests/Trusted Types o creación DOM gradual.

## División futura compatible con ES modules

```text
admin/
  shell.js, state.js, api.js
  bookings.js, conversations.js, outbox.js, reviews.js
  services.js, staff.js, availability.js
  channels.js, business-media.js, growth.js
owner/
  shell.js, businesses.js, business-detail.js
  approvals.js, integrations.js, incidents.js, operations.js
  automation-credits.js, onboarding.js
landing/
  theme.js, content.js, gallery.js
  booking-availability.js, booking-submit.js, confirmation.js
shared/
  auth.js, api.js, dom.js, dialog.js, format.js, a11y.js
```

Estrategia: extraer primero funciones puras y cliente de respuesta; luego un dominio. Mantener un pequeño `legacy-globals.js` que asigne a `window` las funciones exigidas por `onclick` hasta migrar handlers. No introducir bundler/framework como condición.

## Referencias conceptuales

- **Adminator/Gentelella:** densidad de dashboard y patrón shell/sidebar. Útiles para jerarquía; evitar apariencia genérica y plugins/dependencias.
- **Tabler:** claridad de cards, estados y layouts responsive. Adoptar principios, no su framework ni markup.
- **Easy!Appointments:** agenda como herramienta primaria y flujo de reserva. Comparar navegación temporal y contexto de cita, sin copiar su modelo de permisos.
- **GOV.UK Design System:** validación con resumen enfocado, error junto al campo y conservación de respuestas; apropiado para onboarding y formularios largos.
- **Carbon Design System:** notificaciones por nivel de interrupción y listas/tablas operativas; útil para Owner, sin convertir AutonoGrow en una consola corporativa.
- **Material Design 3:** estados con más de un indicador; útil para health/capabilities, manteniendo identidad propia.

Estas fuentes son referencias de comportamiento y accesibilidad. El producto debe mantener la paleta y voz de AutonoGrow, y priorizar comprensión para autónomos frente a la densidad típica de plantillas administrativas.

Enlaces consultados: [Gentelella](https://github.com/ColorlibHQ/gentelella), [Tabler](https://docs.tabler.io/), [Easy!Appointments](https://github.com/alextselegidis/easyappointments), [GOV.UK Design System](https://design-system.service.gov.uk/components/error-summary/), [Carbon Design System](https://carbondesignsystem.com/components/notification/usage/) y [Material Design 3](https://m3.material.io/foundations/interaction/states/overview). Adminator se usa solo como referencia solicitada de patrón de dashboard; no se incorpora código ni dependencia.

## Cobertura de términos técnicos buscados

`health`, token, subscription, webhook, inbox, outbox, retry, reconnect, WABA, IDs Meta, automation, slot, readiness y job aparecen o pueden aflorar en paneles Owner/Admin y tienen propuestas en `05_admin_ux_audit.md` y `06_owner_ux_audit.md`. `provider`, scope, payload y claim no se encontraron como etiquetas dominantes para el cliente en el HTML estático; aparecen principalmente como conceptos de backend/datos o detalle de candidatura. Regla propuesta: si una respuesta futura los expone, traducir primero el efecto (“cuenta no reconocida”, “permisos concedidos”, “detalle enviado”, “identidad verificada”) y mantener el valor crudo solo en detalle Owner seguro.
