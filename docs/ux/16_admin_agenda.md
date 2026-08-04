# Agenda y gestión de reservas del Business Admin — Sprint 5B.2

Fecha: 4 de agosto de 2026.

## Resultado

La sección `bookings` se presenta como **Agenda** y conserva su hash, permisos, contratos DOM y
fuentes de datos. La vista predeterminada es Hoy y la navegación secundaria ofrece únicamente:

1. **Hoy**: un día navegable, ordenado cronológicamente.
2. **Pendientes**: solicitudes `requested` y `pending` que requieren decisión.
3. **Semana**: tira de siete días y detalle legible del día seleccionado.

No se añadió calendario mensual, alta manual de reservas, endpoint ni dependencia frontend.

## Contratos y endpoints reutilizados

Se mantienen `#bookings-list`, `#booking-staff-filter`, `[data-booking-view]`,
`[data-internal-notes]`, `#reschedule-modal`, sus funciones globales y el parámetro
`booking=<id>`.

| Operación | Contrato existente |
| --- | --- |
| Cargar reservas | `GET /api/admin/businesses/{slug}/bookings` |
| Cambiar estado | `PATCH /api/admin/businesses/{slug}/bookings/{id}/status` |
| Guardar notas internas | `PATCH /api/admin/businesses/{slug}/bookings/{id}/internal-notes` |
| Cargar adjuntos | `GET /api/businesses/{slug}/bookings/{id}/attachments` |
| Consultar huecos reales | `GET /api/businesses/{slug}/available-slots` |
| Reagendar la misma reserva | `PATCH /api/bookings/{id}/reschedule` |
| Flujo de reseña existente | endpoints Admin de `review-request` |

La consulta de huecos sigue enviando `service_id`, fecha, `exclude_booking_id` y, cuando existe,
`staff_business_user_id`. El backend continúa validando duración, excepciones, antelación,
solapamientos, negocio, rol y profesional.

## Estados y acciones

Los valores internos no cambian. La interfaz traduce:

| Estado | Texto visible | Acciones de Agenda |
| --- | --- | --- |
| `requested` | Solicitud nueva | Confirmar, reagendar si tiene servicio y rechazar |
| `pending` | Por confirmar | Confirmar, reagendar si tiene servicio y rechazar |
| `confirmed` | Confirmada | Completar, reagendar, cancelar y no presentado |
| `completed` | Completada | Consulta y flujo de reseña ya existente |
| `cancelled` | Cancelada | Consulta |
| `rejected` | Rechazada | Consulta |
| `no_show` | No presentado | Consulta |

Rechazar y cancelar se muestran como conceptos distintos. Confirmar, rechazar, cancelar,
completar, marcar no presentado y confirmar el nuevo horario solicitan confirmación contextual con
cliente, servicio, fecha y consecuencia. Durante una mutación se bloquean todas las acciones de la
reserva para evitar dobles envíos. La autorización efectiva continúa en servidor.

## Cabecera, resumen y filtros

La cabecera muestra fecha o rango, anterior/siguiente, vuelta a Hoy y resumen contextual. Los cuatro
indicadores compactos son Total, Por confirmar, Confirmadas y Completadas.

Los filtros son locales y no generan peticiones:

- profesional;
- estado;
- servicio, combinando el catálogo y los servicios presentes en reservas;
- búsqueda por nombre del cliente;
- restablecimiento conjunto y resumen de filtros activos.

Los filtros permanecen al cambiar de vista o fecha. Un enlace profundo a una reserva los limpia para
garantizar que la tarjeta pueda localizarse. Para `business_staff` se conserva el alcance del servidor
y el filtro de profesional permanece oculto.

## Vistas

### Hoy

Muestra todas las reservas de la fecha seleccionada, incluidos sus estados cerrados, con hora en una
columna estable y orden cronológico. Destaca sin animación continua la próxima cita, la que está en
curso y las solicitudes que requieren decisión. La navegación puede consultar otros días; Hoy vuelve
a la fecha de Madrid utilizada por la aplicación.

### Pendientes

Agrupa exclusivamente `requested` y `pending`, ordena por fecha/hora y muestra la antigüedad basada en
`created_at`. Confirmar queda como acción primaria y el texto de reagendado aclara que abre huecos
disponibles. El vacío diferencia “Todo está revisado” de un filtro sin resultados.

### Semana

El rango comienza en lunes y contiene siete días. Cada selector indica número de citas; la lista
principal muestra el día activo. Este patrón evita comprimir siete tarjetas completas en columnas y
se conserva en tablet y móvil mediante desplazamiento interno de la tira, nunca del documento.

## Tarjeta de cita

La fila prioriza intervalo de inicio/fin, cliente, servicio, duración, profesional y estado. Contacto,
notas del cliente, notas internas y adjuntos quedan en un detalle desplegable para reducir ruido. Los
datos externos usados en HTML —cliente, servicio, profesional, teléfono y notas— pasan por
`escapeHtml`; no se muestran identificadores internos.

## Reagendado

El flujo sigue siendo: día → carga de huecos reales → hueco → revisión → confirmación. El modal añade
servicio, duración y profesional actuales, estados de carga, vacío, reintento seguro y mensaje
específico para conflicto HTTP 409. Un contador de versión evita que la respuesta de un día anterior
sustituya los huecos del día seleccionado más recientemente.

Las fechas disponibles parten del huso configurado en disponibilidad o negocio, con
`Europe/Madrid` como fallback. Las claves se formatean como fechas civiles sin usar `toISOString()`,
evitando que el navegador desplace el día. “En curso” y “Próxima cita” comparan también horas civiles
en ese huso; las reglas horarias siguen en el backend.

## Polling, carga y errores

No existe un segundo temporizador. La Agenda reutiliza la tarea persistente `operations` y
`loadBookings({ background: true })`. Un contador de carga descarta respuestas antiguas. El render de
polling conserva borradores, foco, selección y scroll de las notas internas mediante el snapshot ya
existente; la fecha y los filtros viven fuera del render.

La primera carga reserva espacio con skeleton y texto accesible. Hay estados distintos para agenda sin
citas, pendientes revisados, semana/día vacío, filtros sin resultados, error de reservas, error de
huecos y conflicto de reagendado. Los errores visibles no interpolan cuerpos completos ni trazas.

## Responsive y accesibilidad

- Escritorio: cabecera alineada, cuatro métricas, filtros compactos y fila Hora/Cita.
- Tablet: filtros 2 × n, tira semanal interna y detalles en dos columnas.
- Móvil: título, navegación, tabs, resumen 2 × 2, filtros plegables, una columna y acciones táctiles.
- El modal se convierte en panel inferior, respeta `safe-area-inset-bottom` y bloquea el scroll del body.
- Tabs con `role`, `aria-selected`, roving `tabindex` y teclas izquierda/derecha/Home/End.
- Modal con nombre y descripción, foco inicial, Escape, focus trap, retorno de foco y regiones vivas.
- Estados incluyen texto y marcadores; no dependen solo del color.

## Seguridad

El frontend no amplía permisos ni decide el negocio. Todas las URLs conservan el slug de la sesión o
el ID de la reserva y el backend mantiene `ensure_can_manage_booking`, aislamiento por `business_id` y
validación del slot. Las acciones se ocultan según estado para claridad, pero no sustituyen las
comprobaciones del servidor. Los IDs usados en atributos y handlers se convierten a enteros positivos.

## Pruebas

La suite focalizada `backend/tests/test_admin_agenda.py` cubre vistas, contratos e IDs, traducciones,
orden, filtros, navegación, vacíos, matriz de acciones, bloqueo doble, escaping, endpoint de huecos,
conflicto, accesibilidad del modal, responsive y reutilización del polling.

Comandos de regresión:

```powershell
pytest backend/tests/test_shared_app_shell.py -q
pytest backend/tests/test_admin_polling.py -q
pytest backend/tests/test_admin_dashboard.py -q
pytest backend/tests/test_admin_agenda.py -q
ruff check backend/tests
git diff --check
```

## Validación manual reproducible

Se localizó Edge, pero no había backend en `127.0.0.1:8000`, sesión Admin ni conjunto de datos de
prueba activo. No se alteró la base de datos ni se fingió una sesión para generar capturas sin valor;
por ello no hay capturas en este sprint. Con backend y sesión Admin activos, abrir
`autonogrow-admin/index.html?b=<slug>#bookings` y comprobar en DevTools 1440 × 900, 1024 × 768,
768 × 1024, 390 × 844 y 360 × 800:

1. Hoy con citas, orden, próxima/en curso y navegación de día.
2. Pendientes con confirmar, rechazar y reagendar; luego su estado vacío.
3. Semana, sus siete contadores y selección de día sin scroll horizontal global.
4. Filtros persistentes entre vistas y restablecimiento.
5. Reagendado con huecos, día vacío, error de red y conflicto provocado desde otra sesión.
6. Teclado completo: tabs, apertura, trap, Escape y retorno de foco del modal.
7. Polling durante la edición de notas sin perder borrador, foco, fecha ni filtros.

## Limitaciones deliberadas

- No hay alta manual de reservas porque no existe un flujo Admin compatible.
- No hay calendario mensual ni cuadrícula horaria de intervalos vacíos.
- Si un negocio no expone un huso válido, la Agenda usa el fallback existente `Europe/Madrid`.
- La validación visual y con lector de pantalla sigue pendiente de una sesión Admin reproducible con
  datos de prueba no sensibles.
