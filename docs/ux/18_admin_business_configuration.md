# Configuración del negocio en Business Admin — Sprint 5B.4

Fecha: 4 de agosto de 2026.

## Resultado

La configuración ocasional del negocio deja de competir como cuatro destinos principales independientes. La entrada **Configuración** reúne un resumen y cinco categorías, sin duplicar formularios ni sustituir sus contratos heredados:

```text
Configuración
├── Información
├── Servicios
├── Equipo
├── Horarios y disponibilidad
└── Página pública
```

Antes, `business`, `services`, `staff` y `schedule` aparecían como pestañas principales al mismo nivel que Inicio, Agenda o Mensajes; marca, galería y temas estaban mezclados con los datos básicos. Ahora las pestañas y secciones heredadas siguen en el DOM como compatibilidad, pero una navegación secundaria lleva a los mismos contenedores y campos. Canales, automatización, reseñas y Owner quedan fuera de este sprint.

## Arquitectura y navegación

- Escritorio: navegación secundaria vertical y fija dentro de la vista, con contenido de ancho legible.
- Tablet: la misma navegación pasa a una cuadrícula compacta; no existe un segundo formulario.
- Móvil: lista vertical de categorías, tarjetas en una columna y barra de guardado por encima de la navegación inferior y del `safe-area`.
- Los destinos conservan los hashes y `data-admin-section`: `business`, `services`, `staff` y `schedule`; `public-page` separa visualmente campos que ya pertenecían al mismo payload de ajustes.
- Los antiguos `data-section` siguen presentes y ocultos mediante `admin-tab--legacy` para proteger consumidores existentes.
- La entrada `configuration` está disponible desde la navegación principal y desde **Más** en móvil. Inicio, Agenda y Clientes y mensajes no cambian.

Un listener delegado atiende la navegación de categorías y otro par atiende `input`/`change`. Los listeners se registran una vez en `DOMContentLoaded`, no durante cada render. No se añadió polling.

## Resumen y estados de preparación

El resumen muestra el nombre real del negocio, el número de apartados preparados, la lista de categorías, tareas pendientes reales y un enlace a la landing. No muestra fecha de actualización porque el modelo cargado no proporciona una fecha fiable para todo el conjunto.

Los cinco criterios son deliberadamente mínimos y dependen solo de datos existentes:

| Categoría | Preparado cuando | Estado alternativo |
| --- | --- | --- |
| Información | existe el nombre obligatorio del negocio | `Faltan datos` si falta |
| Servicios | existe al menos un servicio activo | `Faltan datos` si no existe |
| Equipo | existe al menos un miembro activo y reservable | `Faltan datos` si no existe |
| Horarios | el horario semanal real contiene al menos un tramo | `Faltan datos` si está vacío |
| Página pública | el negocio está activo | `Necesita revisión` si está desactivado |

Mientras carga se muestra `Comprobando…`. Un fallo del loader correspondiente muestra `Error al cargar`. La galería se considera parte del estado de Página pública solo para reflejar un error de carga; no se exige ninguna imagen. No se exigen descripciones, fotos, cantidades mínimas ni porcentajes arbitrarios. El resumen usa “N de 5 apartados preparados”.

## Información

Reutiliza los campos existentes de nombre, categoría, titular, descripción, teléfono, ciudad, dirección, horario descriptivo y enlaces de Maps, Instagram y reseñas. El nombre se identifica como obligatorio. Las ayudas distinguen el horario descriptivo visible en la landing del horario que calcula Agenda y señalan qué textos son públicos.

La validación frontend comprueba el nombre y admite en enlaces públicos solo `http` o `https`, sin credenciales embebidas. Los errores se asocian al campo, se resumen al inicio y trasladan el foco al primer campo inválido. El `business_slug` continúa procediendo del parámetro seguro ya existente y no es editable.

## Servicios

El listado sigue usando los servicios reales y separa activos e inactivos. Cada tarjeta muestra nombre, duración, precio visible cuando existe, estado y número de profesionales asociados derivado de los miembros ya cargados; no hace una petición N+1.

Crear y editar conservan `name`, `description`, `price_text`, `duration_minutes` y `active`. La duración se limita a enteros entre 1 y 1440 minutos, igual que el contrato actual. No se ofrece eliminación porque no existe una ruta backend segura para ella. Al desactivar se confirma que dejará de ofrecerse para nuevas reservas y desaparecerá del catálogo público; se aclara que las reservas existentes se conservan.

## Equipo

El alta y edición conservan email, rol, nombre público, `bookable`, `show_schedule`, bio y asignaciones de servicios. La interfaz diferencia explícitamente:

- **Rol de acceso**: permisos `business_staff` o `business_admin` dentro de AutonoGrow.
- **Nombre público / reservable**: identidad y participación del profesional en reservas.

Solo se muestran datos realmente disponibles; no se inventan fotografías, títulos profesionales ni métricas. El horario individual conserva el flujo existente `GET`/`PUT` por profesional. La eliminación sigue siendo el borrado controlado del backend, mantiene la protección del último administrador y abre el diálogo existente cuando hay reservas futuras. El diálogo incorpora Escape, focus trap y retorno de foco.

El modelo de listado no incluye un resumen del horario por profesional, por lo que no se introduce una lectura por miembro ni se inventa uno. Esta limitación queda como deuda explícita.

## Horarios, disponibilidad y reglas

La categoría distingue el horario general y disponibilidad para reservas, las reglas, los horarios por profesional y las excepciones. Los conceptos técnicos se presentan como:

- intervalo de slots → “Cada cuánto puede empezar una cita”;
- buffer → “Margen entre citas”;
- aviso mínimo → “Antelación mínima”;
- avance máximo → “Hasta cuándo se puede reservar”.

Se mantienen zona horaria, minutos y días como valores internos del payload. El editor soporta días cerrados y múltiples tramos. Antes de guardar valida límites numéricos, horas incompletas, cierre anterior o igual a apertura y solapamientos; no filtra silenciosamente un intervalo inválido. Las excepciones conservan fecha, tipo y tramos especiales.

La interfaz explica que los huecos dependen del horario, duración, profesional, reglas y reservas existentes. No calcula huecos ni altera las reglas backend.

## Página pública, temas e imágenes

Página pública reúne el estado activo, logo, texto alternativo, galería, plantilla, paleta y cuatro colores ya existentes. Una tarjeta ligera usa el nombre y titular/descripción cargados; no renderiza HTML del usuario ni emplea `iframe`. **Ver página pública** construye únicamente la ruta local prevista y codifica el slug.

Se preservan las seis plantillas `classic`, `elegant`, `beauty`, `clinic`, `urban` y `minimal`, y las seis paletas `slate_gold`, `rose_beauty`, `emerald_clean`, `blue_clinic`, `amber_barber` y `violet_modern`, además de la personalización ya soportada. Son estilos de una estructura funcional, no seis webs independientes.

Los controles de upload conservan JPEG, PNG y WebP, límites de tamaño, firma real del archivo, máximo de galería, texto alternativo, orden, activación y eliminación que aplica el backend. La interfaz hace además una comprobación temprana del MIME, sin relajar la validación servidor. Las URLs de medios se aceptan solo con protocolo HTTP(S) y origen del frontend o API. La eliminación solicita confirmación.

## Guardado y cambios pendientes

Cada formulario o tarjeta tiene una snapshot independiente. Se comparan únicamente sus campos propios, ignorando ficheros, campos deshabilitados y controles expresamente auxiliares. Los estados visibles son `Sin cambios`, `Cambios sin guardar`, `Guardando`, `Guardado` y `No se pudo guardar`.

- El conjunto de mutaciones bloquea doble envío por formulario.
- Un error mantiene todos los campos y su estado sucio.
- Un guardado correcto actualiza la snapshot después de recargar la respuesta canónica.
- Cambiar de categoría o sección principal pide confirmación solo si el apartado actual tiene cambios.
- `beforeunload` cubre recarga, cierre y cambio de negocio mediante URL.
- Los campos no se destruyen al navegar: las categorías solo cambian visibilidad.
- Las recargas encadenadas de Servicios y Equipo no pisan otra ficha modificada; primero se exige guardarla o revisarla.
- El guardado de Información y Página pública no se mezcla accidentalmente aunque ambos compartan el único payload backend: si el otro bloque está sucio, se detiene la operación.

No hay autoguardado. El mecanismo no toca los borradores propios de Agenda ni Conversaciones.

## Carga, vacíos y errores

Listas y editores mantienen `aria-busy`, texto accesible y espacio inicial. Servicios, Equipo, Horarios, Excepciones y Galería capturan sus errores localmente y ofrecen un reintento del bloque. Un error de Equipo no vacía Servicios; uno de Galería no impide editar la información; uno de Horarios no rompe el resto.

Los vacíos ofrecen solo acciones soportadas: enfocar el alta de servicio, enfocar el alta de miembro o subir una imagen. Horarios cerrados y excepciones vacías se expresan en texto. Los errores generales pasan por mensajes seguros: los detalles técnicos se registran solo en `console.error` y no se interpolan como HTML.

## Endpoints reutilizados

No se creó ni modificó ningún endpoint, método, modelo o payload funcional.

| Área | Método y ruta existente |
| --- | --- |
| Ajustes | `GET/PATCH /api/admin/businesses/{business_slug}/settings` |
| Servicios | `GET/POST /api/admin/businesses/{business_slug}/services`; `PATCH /api/admin/businesses/{business_slug}/services/{service_id}` |
| Equipo | `GET/POST /api/admin/businesses/{business_slug}/staff`; `PATCH/DELETE /api/admin/businesses/{business_slug}/staff/{member_id}` |
| Servicios del profesional | `PUT /api/admin/businesses/{business_slug}/staff/{member_id}/services` |
| Horario del profesional | `GET/PUT /api/admin/businesses/{business_slug}/staff/{member_id}/availability` |
| Disponibilidad | `GET/PATCH /api/admin/{business_slug}/availability-settings` |
| Excepciones | `GET/POST /api/admin/{business_slug}/availability-exceptions`; `DELETE /api/admin/{business_slug}/availability-exceptions/{exception_id}` |
| Medios | `POST /api/admin/businesses/{business_slug}/media/{logo|gallery}`; `DELETE .../media/logo` |
| Galería | `GET /api/admin/businesses/{business_slug}/media/gallery`; `PATCH/DELETE .../media/gallery/{image_id}` |

El backend sigue aplicando autenticación, permisos, roles, aislamiento por negocio, límites y conflictos. La navegación frontend no sustituye esas comprobaciones.

## Accesibilidad y seguridad

- Navegación secundaria con `nav`, nombre accesible y `aria-current`.
- Jerarquía dentro del `h1` estable del shell; cada destino tiene `h2` y sus grupos `h3`/`fieldset`/`legend`.
- Labels persistentes, ayudas, errores `aria-describedby`, resúmenes `role=alert` y foco al primer error.
- Estado comunicado con texto además de color; botones táctiles y foco visible heredado del sistema visual.
- Diálogo de bloqueo de eliminación con `aria-modal`, Escape, focus trap y retorno.
- Todo dato dinámico interpolado en tarjetas pasa por `escapeHtml`; los enlaces usan construcción restringida y los medios validan protocolo/origen.
- No se exponen respuestas crudas, trazas, payloads o IDs técnicos en mensajes de error.

## Responsive y validación manual

La validación automatizada es estructural. En este entorno no había backend autenticado, sesión Admin ni datos reproducibles, por lo que no se generaron capturas ni se afirma una validación visual real.

Con una cuenta `business_admin` de prueba y datos no sensibles:

1. Abrir `autonogrow-admin/index.html?b=<slug>#configuration` a 1440×900 y comprobar resumen, estado de cinco categorías y enlace público.
2. A 1440×900 abrir Servicios, editar sin guardar, cambiar de categoría, cancelar y confirmar que el valor permanece; después guardar y repetir sin aviso.
3. A 1440×900 abrir Horarios, probar día cerrado, dos intervalos válidos, cierre anterior y solapamiento.
4. A 1024×768 revisar tarjetas de Equipo, alta, permisos, asignación de servicios y diálogo de eliminación con teclado.
5. A 768×1024 revisar Información, errores de nombre/URL y foco al primer error.
6. A 390×844 revisar Servicios y Horarios en una columna, objetivos táctiles y barra de guardado sobre la navegación inferior.
7. A 360×800 reproducir un vacío y un fallo parcial por bloque; verificar reintento local y ausencia de scroll horizontal.
8. Recorrer todas las vistas solo con teclado, ampliar al 200/400 % y validar con NVDA o VoiceOver.
9. Probar JPEG, PNG, WebP y un formato inválido; verificar límites reales de tamaño/cantidad en servidor.
10. Cambiar el parámetro de negocio con cambios pendientes y comprobar el aviso antes de abandonar.

## Pruebas y límites

`backend/tests/test_admin_business_configuration.py` fija la arquitectura, navegación, criterios de preparación, campos críticos, ausencia de IDs duplicados, endpoints, validaciones, seis temas, uploads, escaping, URLs, dirty state, errores parciales, responsive estructural y accesibilidad. Las suites existentes cubren shell, polling, Dashboard, Agenda, Conversaciones, servicios/personal, scheduling, permisos y flujos backend.

Limitaciones conocidas:

- el horario individual se mantiene en el diálogo secuencial heredado porque no existe un editor masivo ni un resumen en el modelo del listado;
- `price_text` continúa siendo texto visible porque ese es el contrato existente; no se inventa validación monetaria;
- Información y Página pública comparten necesariamente el endpoint y payload completo de ajustes, por lo que se coordinan para no sobrescribir cambios pendientes;
- falta la comprobación visual autenticada y con tecnologías de asistencia indicada arriba;
- modularizar globalmente `admin.js` queda fuera del alcance para evitar afectar Dashboard, Agenda y Conversaciones.
