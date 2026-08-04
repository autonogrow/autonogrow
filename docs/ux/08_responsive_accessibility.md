# 08 — Responsive y accesibilidad inicial

## Limitación de validación

No había navegador ejecutable ni Playwright/Selenium en el entorno. Los resultados siguientes proceden de HTML/CSS/JS y son reproducibles por inspección de reglas; cuando dependen del contenido real se marcan **probables**. No se afirma una captura ni una prueba visual inexistente.

### Protocolo de reproducción pendiente

Para cada app: iniciar backend con datos representativos, autenticar cada rol, fijar viewport 360×800, 390×844, 768×1024, 1024×768 y 1440×900; recorrer teclado, zoom 200/400 %, contenido largo, error, vacío y carga. Probar los seis temas de landing y al menos 10 negocios en Owner.

## Matriz por anchura

| App/vista | Anchura | Hallazgo estático | Cómo reproducir | Gravedad |
|---|---:|---|---|---|
| Owner / pestañas | 360, 390 | **Probable overflow**: `.tabs` es `inline-flex` sin wrap ni overflow-x | abrir Owner y medir `scrollWidth` de tabs/documento | Alta |
| Owner / canales | 360, 390 | **Regla confirmada**: `.owner-channel-control-grid` conserva 2 columnas porque se declara después de los media queries y no recibe override | abrir una tarjeta con ambos canales; inspeccionar columnas | Alta |
| Owner / onboarding | 360, 390 | a <=900 los 15 pasos se convierten en grid de 3 columnas; <=600 no lo corrige | abrir sesión en paso intermedio y navegar con teclado | Alta |
| Owner / tarjetas | 360–768 | mucha información y acciones pequeñas; los subpaneles pasan a una columna, pero la longitud crece notablemente | negocio con users, candidates, health y credits | Media-alta |
| Owner / operaciones | 360–768 | `<pre>` puede forzar scroll interno/horizontal si no envuelve todos los valores | cargar error con texto/ID largo | Media |
| Admin / navegación | 360, 390 | overflow-x está previsto; la pestaña activa puede quedar fuera de vista tras navegación programática | abrir un hash lejano/teclado y comprobar auto-scroll | Media |
| Admin / agenda | 360, 390 | tarjetas y controles apilan; grupos de acciones pueden producir scroll/altura excesiva con texto largo | cita con adjuntos, notas, reseña y todos los botones | Media |
| Admin / conversaciones | 360, 390 | <=820 se apila lista e hilo; se pierde simultaneidad y el usuario puede quedar lejos de la conversación seleccionada | seleccionar conversación profunda y responder | Alta |
| Admin / horarios | 768–820 | breakpoint convierte grid; justo por encima de 820 se mantienen 5 columnas, posible cliff | redimensionar 819→821 con ventanas largas | Media |
| Admin / modales | todas pequeñas | overlay tiene scroll, pero reschedule no gestiona foco; teclado puede navegar al fondo | abrir modal, Tab/Shift+Tab/Escape | Alta |
| Landing / carrusel | todas | indicadores son 10×10 px: por debajo del objetivo mínimo 24×24 de WCAG 2.2 salvo excepción | inspeccionar botón/usar touch emulation | Alta |
| Landing / 768 | 768 | breakpoint principal es 760: a 768 conserva layout de escritorio justo antes del cambio | texto largo, formulario y hero a 768 portrait | Media |
| Landing / reserva | 360, 390 | slots siguen en dos columnas; el texto puede envolver, pero requiere prueba con locales/horas | elegir servicio con muchos huecos | Media |
| Customer | 360, 390 | grid colapsa por debajo de 680; estructura simple | probar textos y reservas largas | Baja |
| Todas | 1024 | contenedores desktop y nav horizontal; Owner/Admin aún presentan mucha densidad | tablet landscape con zoom 200 % | Media |
| Todas | 1440 | max-width Admin 1180, Owner 1240, Landing ~1170; no hay overflow previsto, pero aumenta espacio lateral y navegación sigue plana | monitor desktop con pocos/muchos datos | Baja |

No hay tablas de datos en el frontend actual; la preocupación “tablas responsive” no aplica todavía. Sí hay listas con estructura tabular simulada, especialmente Owner jobs/incidents, que pierden alineación al apilar.

## Auditoría WCAG 2.2 AA inicial

### Prioridad 1 — bloqueantes

1. **Diálogo de reagenda:** `#reschedule-modal` no tiene `role="dialog"`, `aria-modal`, nombre accesible, foco inicial, trampa de foco, Escape ni restauración de foco. El modal de bloqueo de personal sí tiene semántica básica, pero comparte las carencias de gestión de foco.
2. **Foco visible:** no existe un tratamiento transversal `:focus-visible` para botones/enlaces/controles. Algunos inputs tienen focus, pero no garantiza que todos los interactivos con teclado sean perceptibles (2.4.7 y 2.4.11 deben verificarse).
3. **Tabs:** Admin declara `aria-selected` sin patrón completo `tablist/tab/tabpanel`, `aria-controls` ni navegación con flechas; Owner usa botones visuales sin roles/estado accesible. Elegir navegación convencional o implementar el patrón entero.
4. **Mensajes dinámicos:** cargas, errores, conexión y guardado suelen actualizar nodos sin `role=status`, `role=alert` o `aria-live`; un lector puede no anunciar el resultado.
5. **Objetivo táctil del carrusel:** 10×10 px no cumple el mínimo 24×24 de WCAG 2.2 2.5.8 en su forma actual. Aumentar hit area manteniendo el punto visual.

### Prioridad 2 — alta

6. Añadir un enlace “Saltar al contenido” y landmarks/nav con nombres cuando hay varias navegaciones.
7. Definir orden de encabezados por pantalla tras reorganizar; el HTML usa headings, pero el render dinámico puede saltar niveles y cada sección oculta conserva su propio `h2`.
8. Asociar feedback/error a su control con `aria-describedby`, no solo proximidad/color. Conservar datos introducidos y resumir errores en formularios largos.
9. Evitar `alert`, `prompt` y `confirm` para procesos complejos/destructivos; son nativos pero no explican impacto ni soportan el patrón de revisión requerido.
10. Revisar contraste por combinación real de los seis temas y colores personalizados. El recuento de colores no demuestra cumplimiento; debe calcularse texto/fondo/estado/foco.
11. Los estados suelen incluir texto además de color —fortaleza—, pero “active” del carrusel y algunos bordes de salud dependen visualmente del color. Añadir estado textual/`aria-current`.
12. Añadir nombre accesible a botones de carrusel anterior/siguiente si su texto es solo un símbolo. Los indicadores sí generan `aria-label`.

### Prioridad 3 — media

13. Tamaño recomendado de acciones frecuentes: aunque botones Owner (~35 px) y Admin (~38 px) superan el mínimo 24, acercarse a 44×44 mejora móvil y usuarios con movilidad reducida.
14. Probar zoom 400 % y reflow; `pre`, nav horizontal, grillas de canales y pasos son los candidatos principales.
15. Revisar alt: logos pueden usar nombre del negocio; fotos decorativas pueden llevar alt vacío; galería necesita el alt guardado, no “imagen” genérica.
16. Formularios dinámicos no siempre están dentro de `<form>`; esto vuelve inconsistente Enter, validación y agrupación. Migrar por flujo sin cambiar eventos hasta probar.
17. Marcar enlaces externos/que abren otra aplicación cuando sea relevante, sin forzar nueva pestaña.
18. Añadir `autocomplete` apropiado a nombre, teléfono, email, dirección; no aplicarlo a credenciales que no deben persistir.

## Aspectos presentes y aprovechables

- Todos los documentos principales tienen idioma español y título de página.
- La mayoría de controles usa `<button>`, `<input>`, `<select>` y `<label>` reales.
- El progreso diario actual actualiza `aria-valuenow` desde `renderGrowth()`.
- Los estados críticos suelen combinar color y texto.
- Admin respeta `prefers-reduced-motion` en parte de sus estilos.
- El carrusel genera nombres para indicadores; el modal de personal ya tiene `role=dialog` y `aria-labelledby`.

## Checklist de aceptación futuro

- Teclado completo sin pérdida/trampa de foco; Escape y retorno en diálogos.
- Nombre, rol y estado correctos en Accessibility Tree.
- Reflow sin scroll bidimensional a 320 CSS px/zoom equivalente, salvo contenido esencial.
- Contraste AA medido para texto, controles, estados y foco en cada tema/color permitido.
- Objetivos de al menos 24×24, preferencia 44×44 en acciones primarias.
- Errores concretos junto al campo y resumen enfocado en formularios largos.
- NVDA+Firefox/Chrome en Windows y VoiceOver+Safari móvil antes del piloto.

## Anclas de evidencia

- `.tabs` Owner sin overflow/wrap: `autonogrow-owner/styles.css:24`.
- Breakpoints Owner y grid declarado después: `autonogrow-owner/styles.css:156-160`.
- Breakpoints Admin: `autonogrow-admin/styles.css:1169`, `:1215`, `:1407`, `:1451` y `:1457`.
- Modal de reagenda sin atributos de diálogo frente al modal de personal: `autonogrow-admin/index.html:541` y `:560`.
- Indicador de galería 10×10: `autonogrow-landing/styles.css:55`; su `aria-label` se crea en `script.js:399`.
- Progreso Admin con valor inicial: `autonogrow-admin/index.html:150`; actualización accesible en `admin.js:330`.
