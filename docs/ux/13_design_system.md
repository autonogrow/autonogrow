# 13 — Sistema visual compartido

## Alcance de 5A.2

El sistema vive en `autonogrow-shared/` y se carga de forma aditiva en Admin y Owner. Las clases anteriores permanecen en el HTML y el JavaScript de dominio conserva sus selectores. Customer y Landing no cargan todavía estas hojas: quedan como consumidores futuros para evitar cambios visuales no validados en este sprint.

```text
autonogrow-shared/
├── tokens.css          variables de diseño
├── base.css            base acotada a .ag-body/.ag-app
├── components.css      primitivas reutilizables
├── layout.css          shell, sidebar, topbar y contenido
├── responsive.css      drawer y navegación móvil
├── accessibility.css   foco, skip link, reduced motion
└── app-shell.js        interacción mínima del drawer
```

## Tokens

### Marca y semántica

| Token base | Valor | Uso |
|---|---|---|
| `--ag-color-blue-500` | `#1E90FF` | identidad y foco |
| `--ag-color-blue-700` | `#0069B8` | acción primaria con mayor contraste sobre blanco |
| `--ag-color-coral-500` | `#FF6F61` | acento moderado, no CTA principal |
| `--ag-color-green-500` | `#2ECC71` | identidad de éxito; texto usa verde más oscuro |
| `--ag-color-ink` | `#1A1A1A` | texto principal |
| `--ag-color-canvas` | `#F5F5F5` | fondo de aplicación |

Los estados disponen de pareja texto/fondo para info, éxito, aviso y peligro. El estado no se expresa solo mediante color: badges incluyen punto/label, alertas incluyen marca y texto, y la navegación activa combina fondo, indicador lateral y peso.

### Tipografía

- Títulos: `Montserrat`, después Inter/Segoe UI/Roboto/Helvetica/Arial.
- Interfaz: `Inter`, después Segoe UI/Roboto/Helvetica/Arial.
- Escala: xs, sm, md, lg, xl, 2xl y 3xl; line-height tight/body/loose.

No existían archivos autorizados de Montserrat o Inter. No se añadieron binarios ni peticiones a Google Fonts para evitar bloqueo, dependencia externa y exposición de IP. Si el sistema operativo no tiene las fuentes, se usa el fallback local. La incorporación futura de fuentes deberá decidir alojamiento propio, licencias, subconjuntos WOFF2, preload solo de pesos usados y política CSP/cache.

### Espacio, forma y layout

- Escala: 4, 8, 12, 16, 20, 24, 32, 40, 48 y 64 px.
- Radios: 8, 12, 16, 20 px y pill.
- Controles: 44 px normal/táctil, 36 px pequeño y 52 px grande.
- Sidebar: 272 px; topbar mínimo 84 px; contenido máximo 1280 px.
- Z-index: sticky, navegación móvil, backdrop, drawer, modal y toast.
- Movimiento: 120/200 ms con curva estándar y anulación bajo reduced motion.

Los breakpoints se documentan como 640 y 1024 px. Aunque se exponen variables informativas, CSS no permite usar custom properties directamente en condiciones `@media` de forma interoperable, por lo que los valores aparecen también en `responsive.css`.

## API de componentes

### Botones

```html
<button class="ag-button ag-button--primary" type="button">Guardar</button>
<button class="ag-button ag-button--secondary" type="button">Cancelar</button>
<button class="ag-button ag-button--danger" type="button">Suspender</button>
```

Variantes: `--primary`, `--secondary`, `--ghost`, `--danger`, `--icon`, `--small`, `--large`. `disabled` y `aria-disabled` tienen apariencia no interactiva; `aria-busy=true` añade loader sin cambiar el label accesible.

### Tarjetas

```html
<article class="ag-card ag-card--interactive">
  <header class="ag-card__header">…</header>
  <div class="ag-card__body">…</div>
  <footer class="ag-card__footer">…</footer>
</article>
```

Variantes `--warning` y `--danger` añaden un borde semántico. En 5A.2 se aplican como muestra a métricas/resumen sin sustituir las clases `stat-card`, `growth-summary-card` o `summary-card`.

### Badges

`ag-badge` con `--neutral`, `--info`, `--success`, `--warning`, `--danger`. Owner añade estas clases a `health-badge` y `state-badge` generados, conservando las clases/estados originales.

### Formularios

```html
<label class="ag-field ag-label">
  Nombre
  <input class="ag-input" aria-describedby="name-help">
  <span id="name-help" class="ag-help">Nombre visible.</span>
</label>
```

API: `ag-field`, `ag-label`, `ag-input`, `ag-select`, `ag-textarea`, `ag-help`, `ag-field-error`, `ag-form-actions`. Se contemplan disabled, readonly, `aria-invalid`, `data-state=error|success` y focus visible. La migración de errores por campo se hará dentro de cada sprint funcional.

### Feedback y estados

- Alertas: `ag-alert` más `--info|success|warning|danger`.
- Vacío: `ag-empty-state`, icon/title/description/actions.
- Carga: `ag-loader`, `ag-skeleton` y `ag-skeleton--card` con altura estable.
- Toast: `ag-toast-region` y `ag-toast`; 5A.2 unifica la apariencia, no reemplaza la lógica actual ni hace auto-dismiss.
- Modal: `ag-modal-overlay`, `ag-modal`, header/body/actions/close y `ag-modal--danger`.

El modal de reagenda conserva `#reschedule-modal`, `#reschedule-modal-content` y callbacks actuales, y ahora tiene `role=dialog`, `aria-modal`, `aria-labelledby` y cierre con nombre accesible. Staff removal conserva sus contratos y adopta variante peligrosa. Focus trap, foco inicial, Escape y retorno al disparador siguen pendientes de un módulo de diálogo específico.

## Iconografía

El shell usa SVG inline pequeño, `fill=none` y `currentColor`; los contenedores tienen `aria-hidden=true`. Los botones que contienen solo icono tienen `aria-label`. No se añadió librería ni fuente de iconos.

## Compatibilidad gradual

Ejemplos reales:

```html
<button class="btn btn-primary ag-button ag-button--primary">Actualizar</button>
<button class="button button-secondary ag-button ag-button--danger">Cambiar mantenimiento</button>
```

La clase legacy permanece para no romper estilos, búsquedas o HTML generado. La hoja shared se carga después de la hoja de aplicación para que una clase `ag-*` explícita pueda demostrar el nuevo aspecto. No se aplican reglas globales a páginas legales porque estas no cargan los nuevos archivos y la base está acotada a `.ag-body`/`.ag-app`.

## Migración recomendada

1. Añadir clase shared junto a la legacy y verificar todos los estados.
2. Migrar un dominio/pantalla, incluidos render templates JS.
3. Añadir prueba estática/visual/teclado.
4. Buscar uso de la clase legacy en HTML, JS, CSS y tests.
5. Retirar la clase/regla antigua solo en un cambio posterior explícito.

## Limitaciones

- No se midió contraste visual en navegador ni con colores de negocio personalizados.
- No se cargan todavía Montserrat/Inter como webfonts.
- Customer/Landing no están integrados para evitar rediseñarlos antes de sus sprints.
- Toast y loader son API CSS; no sustituyen estados actuales automáticamente.
- El sistema de modal es visual/semántico, no un gestor de foco completo.

