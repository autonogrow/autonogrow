# 26 — Landing pública y experiencia de reserva

Fecha de corte: 5 de agosto de 2026. Sprint 5E.1.

## Punto de reanudación

El trabajo se reanudó con la landing ya reorganizada en identidad, servicios, equipo, galería, ubicación, reseñas, contacto y una reserva guiada. Ya existían una única fuente de estado de reserva, invalidación de fecha/slot al cambiar servicio o profesional, tratamiento no optimista del conflicto y resultado fiel a `requested`. Desde ese punto se completaron **Mis citas**, la auditoría de contratos, las pruebas focalizadas y este cierre documental; no se reinició ni se sustituyó la arquitectura válida.

## Estructura anterior

La página anterior tenía hero, cuatro accesos rápidos, descripción, servicios, un carrusel, un formulario largo y contacto. Servicio, profesional, calendario, datos, adjuntos y envío convivían en una sola superficie. Los errores utilizaban `alert`, algunos detalles backend podían terminar como texto y el resultado decía “Cita creada correctamente” aunque el servicio de reservas guarda `requested`.

El portal cliente anterior listaba tarjetas próximas/históricas y editaba el perfil. Mostraba el estado interno sin traducir, no tenía detalle y filtraba errores con un mensaje backend genérico.

## Arquitectura final

```text
Landing
├── Identidad y propuesta
├── Servicios reservables
├── Equipo público
├── Galería pública
├── Horario y ubicación
├── Reseñas externas
├── Reserva guiada
│   ├── Servicio
│   ├── Profesional
│   ├── Fecha y hora
│   ├── Datos
│   ├── Revisión
│   └── Resultado
└── Contacto y pie legal

Mis citas
├── Sesión
├── Perfil de contacto
├── Próximas
├── Historial
└── Detalle seguro
```

Solo hay un `booking-form`, un listener de envío y un objeto `bookingState` con `business`, `service`, `staff`, `date`, `slot`, `customer` y `booking`. El antiguo flujo no permanece cargado en otro archivo.

## Fuentes y contratos

| Pantalla | Fuente | Endpoint | Estado vacío | Estado de error |
|---|---|---|---|---|
| Landing | negocio activo | `GET /api/businesses/{slug}` | no aplica | negocio no disponible o reintento de conexión |
| Servicios | servicios activos verificados con personal público compatible | `GET /api/businesses/{slug}/services` + `GET /api/businesses/{slug}/staff?service_id={id}` | no hay servicios disponibles para reserva online | comprobación fallida o parcial; nunca se asume reservabilidad |
| Equipo | personal público | `GET /api/businesses/{slug}/staff` | sección omitida | aviso parcial; reserva vuelve a consultar por servicio |
| Galería | medios activos | `GET /api/businesses/{slug}/media/gallery` | sección omitida | aviso parcial; resto disponible |
| Horario habitual | negocio | campo público `schedule` | “no ha publicado horario” | se conserva la ficha principal |
| Reglas de fecha | configuración pública | `GET /api/businesses/{slug}/availability-settings` | fallback conservador de 14 días | se explica que manda la respuesta del negocio |
| Fechas | disponibilidad backend | `GET /api/businesses/{slug}/calendar-days` | no hay fechas en el periodo | no se pudieron comprobar las fechas |
| Slots | disponibilidad backend | `GET /api/businesses/{slug}/available-slots` | no hay horarios para la fecha | no se pudieron comprobar los horarios |
| Resultado | creación | `POST /api/businesses/{slug}/bookings` | no aplica | validación, conflicto, límite, sesión o general |
| Adjuntos | token de gestión devuelto al crear | `POST /api/businesses/{slug}/bookings/{id}/attachments` | sin imágenes | reserva conservada y fallo de imágenes explícito |
| Mis citas | sesión autenticada | `GET /api/customer/bookings` | próximas e historial vacíos por separado | sesión caducada o reintento seguro |
| Perfil | sesión autenticada | `GET/PATCH /api/customer/profile` | campos opcionales vacíos | mensaje filtrado; datos permanecen en formulario |

## Matriz de acciones

| Acción | Estado inicial | Resultado backend | Mensaje visible | Refresco |
|---|---|---|---|---|
| Cargar landing | slug validado | negocio activo | identidad pública | fuentes secundarias en paralelo |
| Seleccionar servicio | catálogo activo | personal compatible | duración/precio y paso profesional | invalida profesional si no es compatible, fecha y slot |
| Seleccionar profesional | lista compatible | selección local válida | nombre o asignación neutral | invalida fecha y slot |
| Consultar fechas | servicio + personal neutral/concreto | días backend | estados textuales por día | cache por clave y versión de respuesta |
| Consultar slots | fecha backend seleccionable | slots backend | botones de hora | cache por clave; forzado tras conflicto |
| Crear anónima | datos válidos sin sesión | `requested` | Solicitud enviada | no optimista; limpia datos solo tras éxito |
| Crear autenticada | sesión existente | `requested`, vinculada | acceso a Mis citas | no optimista |
| Abrir detalle | cita propia ya listada | sin nueva petición por ID | estado y datos públicos del negocio | usa índice efímero, no URL predecible |
| Reagendar | `can_manage: false` | no autorizado por contrato cliente | contactar con el negocio | no se ofrece acción falsa |
| Cancelar | `can_manage: false` | no existe contrato cliente | contactar con el negocio | no se ofrece acción falsa |
| Abrir mapa/reseñas/Instagram | URL pública validada | navegación externa | nombre de la acción | pestaña segura |
| Abrir WhatsApp | teléfono público válido | navegación externa | escribir al negocio | sin mensaje con datos sensibles |

## Carga del negocio, preview e inactivos

El slug acepta únicamente letras ASCII, números y guiones, y se codifica también al construir la ruta. El endpoint público filtra `Business.status == "active"`; por tanto inexistente, pendiente, suspendido o archivado producen el mismo estado seguro y no revelan el estado interno. La página parte de `noindex, nofollow` y solo cambia a `index, follow` después de recibir un negocio activo.

No existe contrato público para convertir la landing en preview Owner. El preview real sigue siendo `GET /api/owner/businesses/{id}/preview`, autenticado y textual dentro del Owner. La landing no interpreta un parámetro `preview`, no consume ese endpoint y no simula publicación privada. Este límite evita que un query string inventado habilite datos o reservas.

## Identidad, hero y navegación

Nombre, categoría, titular, descripción, ciudad, logo, plantilla y colores proceden del negocio. Los colores solo se aplican si cumplen `#RRGGBB`; hay fallback, texto claro/oscuro calculado para el primario y foco independiente. Las imágenes admiten HTTPS/HTTP o `/uploads/`, reservan tamaño, tienen `alt` y se retiran individualmente si fallan.

El hero prioriza nombre, propuesta, ciudad, disponibilidad comprensible, **Reservar** y **Contactar**. La navegación por anclas muestra solo secciones disponibles, tiene menú móvil, `aria-expanded`, Escape, cierre al navegar y sección actual mediante `IntersectionObserver`. Conserva `?b=slug` y el acceso a Mis citas.

## Servicios y precios

El endpoint `GET /api/businesses/{slug}/services` expone actualmente servicios activos. Tras validar la estructura básica de cada elemento, la landing comprueba su reservabilidad mediante `GET /api/businesses/{slug}/staff?service_id={id}`. Este segundo endpoint usa `get_public_bookable_staff()` y solo devuelve profesionales activos, reservables, con horario público, no eliminados y asociados al servicio activo. Un servicio sin al menos un profesional público compatible no aparece en el catálogo ni entra en el flujo.

La colección canónica `bookingState.business.services` permanece vacía durante la comprobación y recibe exclusivamente los servicios verificados. Catálogo, selector, CTA y validación previa al envío consumen esa misma colección; no existe una segunda lista divergente. Las comprobaciones usan una caché de promesas solo en memoria, compartida con la selección posterior, tres workers como máximo y versiones de carga para descartar resultados de otro negocio. Los fallos no se convierten en servicios reservables: si todos fallan se muestra un error reintentable y, si solo falla una parte, se enseñan exclusivamente los verificados.

El frontend no confía en `visible`, `bookable` ni `archived_at`, porque `ServiceOut` no expone esos campos. La mejora futura recomendable es que el propio endpoint de servicios filtre los servicios efectivamente reservables o exponga explícitamente esas tres señales. Este sprint no modifica `backend/app`; el backend continúa siendo la autoridad final al crear la reserva.

## Equipo

La sección usa `public_name`, `bio` y `avatar_url`; no muestra correo, roles, membresía ni IDs. En reserva, la selección reutiliza el resultado ya obtenido para `service_id` y evita una petición duplicada. “Cualquier profesional disponible” envía `staff_business_user_id` solo cuando existe selección concreta; con valor neutral el backend decide una persona compatible.

## Galería

Los medios se cargan de forma diferida y cada fallo se aísla. El visor es un diálogo con `aria-modal`, foco inicial, trampa de Tab, Escape, flechas, cierre por fondo y retorno de foco. No se muestra el nombre interno del archivo ni se bloquea la reserva.

## Horarios y ubicación

El texto `schedule` se identifica como horario habitual. Fechas y slots se presentan aparte y siempre dependen de backend; no se infiere “abierto ahora”. Dirección, ciudad y mapa solo aparecen si existen. Todas las URLs externas pasan por lista de protocolos y usan `rel="noopener noreferrer"`.

## Reseñas, contacto y canales

No se inventan estrellas, puntuaciones, testimonios ni recuentos. Si hay `reviews_url`, se ofrece el enlace externo; si no, la sección se omite. Contacto usa únicamente teléfono, WhatsApp e Instagram expuestos por el `BusinessOut` actual. La presencia del enlace no se describe como integración o automatización.

## Flujo y estado frontend

`bookingState` es la autoridad única. Cambiar servicio invalida fecha, slot y profesional incompatible; cambiar profesional invalida fecha y slot; cambiar fecha invalida slot. `landingState` guarda solo estado de presentación, caches y versiones de carga. No se guardan datos personales en almacenamiento, URL, fragmentos o logs.

El flujo mueve foco al título al entrar desde la landing, expone progreso textual y permite volver. La disponibilidad se consulta bajo demanda. Personal, calendario y slots tienen contadores de versión para descartar respuestas obsoletas; calendario y slots se cachean por servicio/profesional/rango o fecha para evitar duplicados.

## Fecha, slots y concurrencia

El día inicial se obtiene en la zona horaria pública del negocio; el horizonte usa `max_days_ahead`. Los estados `available`, `special`, `full`, `closed` y `past` se expresan con texto, no solo color. Solo `available` y `special` son seleccionables.

Un 409 no produce éxito ni reintenta otra hora. Se borra únicamente el slot, se conserva `bookingState.customer`, se vuelve al paso horario y se fuerza una nueva consulta. “Sin huecos” y “no se pudo comprobar” son estados distintos.

## Datos, privacidad y revisión

El payload conserva los campos reales: nombre obligatorio; teléfono, notas, profesional y adjuntos opcionales. No se inventa email ni consentimiento comercial. Los campos vacíos opcionales se omiten. Las imágenes se validan por cantidad, MIME y tamaño antes del envío.

La finalidad y los enlaces legales existentes aparecen junto a los datos. La revisión contiene negocio, servicio, duración, precio, profesional, fecha, hora, zona, nombre, contacto y notas. Cada bloque permite editar. El texto previo al envío afirma que será una solicitud.

## Creación y resultado

Un guard bloquea doble envío. La interfaz espera la respuesta y nunca cambia el estado local antes de ella. Timeout, 400/422, 401/403, 404, 409, 429 y 5xx tienen mensajes filtrados. Los adjuntos se suben después de crear la reserva con el token efímero ya soportado; si fallan, se explica que la solicitud sí quedó registrada.

`create_booking_request()` asigna actualmente `status="requested"` sin consultar `auto_confirm_bookings`; además, el endpoint público de settings no expone esa regla. Por ello el resultado dice **Solicitud enviada**. Existe traducción defensiva para estados devueltos futuros, pero nunca se promete confirmación. No se muestran booking ID, business ID, customer ID ni tokens.

## Mis citas y detalle

El portal conserva la autenticación Google, carga perfil y reservas en paralelo, separa próximas e historial, muestra contadores y estados traducidos, y distingue sesión caducada. Los vacíos explican qué aparecerá en cada zona. La consulta backend filtra por `customer_user_id == user.id` o email de la sesión; el frontend no acepta un ID en URL.

El detalle se abre desde el array ya autorizado mediante un índice efímero, no un identificador predecible. Es un diálogo con foco, Escape, trap y retorno. Solo muestra negocio, servicio, fecha/hora, estado, dirección y canales públicos seguros.

## Reagendado y cancelación

El backend tiene reagendado para personal/administración mediante `require_booking_business_access`; no es autorización de cliente. `/api/customer/bookings` devuelve expresamente `can_manage: false`. No existe endpoint cliente de cancelación. Por tanto el portal no muestra botones ni construye peticiones de reagendado/cancelación, no solicita fecha manual, no cambia estados y no finge políticas. El detalle dirige al contacto público.

La funcionalidad pedida “cuando esté permitida” requiere un contrato backend futuro con capacidad por cita, reglas, protección IDOR/CSRF y endpoints cliente. Añadir solo la interfaz sería inseguro.

## Estados y errores

Landing y portal centralizan `requested`, `pending`, `confirmed`, `completed`, `cancelled`, `rejected` y `no_show`. Un valor desconocido se convierte en “Estado actualizado”, no se imprime crudo. Se distinguen negocio no disponible, ausencia de contenido, fallo de fuente secundaria, error de fechas, sin slots, error de slots, conflicto, sesión, validación, autorización, rate limit y fallo temporal.

Los errores de formulario usan resumen focalizable, `aria-invalid` y `aria-describedby` asociado. No se muestran `detail` arbitrarios, responses, trazas o endpoints.

## Navegación contextual

- landing → servicio → reserva con el servicio;
- equipo → reserva, conservando candidato y comprobando compatibilidad tras elegir servicio;
- landing → reserva/contacto/ubicación/reseñas;
- resultado → Mis citas, contacto o inicio;
- Mis citas → detalle → landing/mapa/WhatsApp;
- reagendado/cancelación no aparecen porque `can_manage` es falso.

## SEO y rendimiento

Título, description y Open Graph básico se actualizan con datos públicos saneados. No se inventa canonical. El portal y el estado inicial/no disponible/resultados usan noindex. Como HTML estático, los metadatos del negocio se aplican con JavaScript: esto no equivale a SSR y algunos crawlers pueden conservar los valores iniciales.

La ficha principal se obtiene antes que las fuentes secundarias. Estas se resuelven en paralelo y un fallo no borra datos ya mostrados. Galería usa lazy loading, disponibilidad se carga bajo demanda, caches evitan peticiones duplicadas, versiones descartan respuestas antiguas y no hay polling ni carga del portal desde la landing.

## Responsive

La estructura contempla una columna en móvil, grids 1/2/3 columnas, menú compacto bajo 820 px, inputs de 16 px, calendario 7/4/3 columnas, slots 3/2 columnas, CTA con safe area y acciones apilables. Los diálogos usan `100dvh`, el body bloquea scroll solo al abrirlos y no se usan tablas. Los cortes cubren estructuralmente 360, 390, 768, 1024, 1280 y 1440 px.

## Accesibilidad

Se añadieron skip links, un `h1` por estado, landmarks, navegación etiquetada, botones reales, foco visible, jerarquía, labels, fieldsets, legends, progreso con `aria-current`, estados textuales, `aria-busy`, errores asociados y diálogos accesibles. Calendario y slots son botones con `aria-pressed`. Menú y diálogos responden a Escape; los diálogos atrapan y devuelven foco. `prefers-reduced-motion` elimina transiciones relevantes y los objetivos principales miden al menos 44–48 px.

## Seguridad

Todo contenido dinámico usa `textContent`/nodos; no hay `innerHTML`, persistencia personal, logs de bodies ni secretos. Slug, URLs, colores, teléfonos e imágenes se validan. Los IDs se usan solo dentro de peticiones o memoria y nunca como contenido. El portal no navega por booking ID; la autoridad de aislamiento permanece en backend. Mutaciones usan el cliente compartido con cookies y CSRF. No se añadieron endpoints, modelos, migraciones ni cambios backend funcionales.

## Pruebas

`backend/tests/test_public_landing_booking_ux.py` inspecciona arquitectura, contrato activo, noindex/preview, identidad, colores, imágenes, servicios/precios, equipo, galería, ubicación, contacto, estado único, invalidaciones, disponibilidad real, carreras, caches, vacíos, errores, conflicto, privacidad, revisión, `requested`, doble envío, resultado, portal, aislamiento, detalle, ausencia justificada de gestión, estados, SEO, responsive, accesibilidad, escaping, secretos, persistencia, endpoints y flujo duplicado.

Se ejecutan además pruebas existentes de negocio público, reservas, disponibilidad, personal, aislamiento, CSRF, rate limit, uploads, preview y activación, seguidas de la suite completa. El entorno no dispone de Node ni navegador; la sintaxis/comportamiento se cubre con la suite estructural y la validación visual queda diferida.

Resultados de cierre:

- focalizada 5E.1: **27 passed**;
- selección funcional relacionada: **103 passed, 25 skipped, 21 subtests passed**;
- `ruff check backend/tests`: **All checks passed**;
- suite completa: **606 passed, 26 skipped, 53 subtests passed**;
- `git diff --check`: sin errores (solo avisos informativos de conversión LF/CRLF del entorno Windows).

Los avisos de pytest son deprecaciones preexistentes de fecha/SQLAlchemy/Starlette y dos avisos de colección; no se relajaron pruebas.

## Validación visual pendiente (5F.1)

Pendientes sin fabricar datos ni capturas: landing/servicios/reserva/revisión/resultado a 1440×900; landing/calendario a 1024×768; reserva a 768×1024; hero/servicios/calendario/datos/revisión/resultado a 390×844; conflicto y Mis citas a 360×800. También quedan autenticación real, varios negocios, zoom 200/400 % y lector de pantalla.

## Limitaciones y deuda

1. No hay preview visual público autenticado: Owner conserva preview textual privado.
2. Settings públicos no exponen `auto_confirm_bookings`, cancelación o reagendado; creación guarda siempre `requested`.
3. El portal no recibe zona horaria, profesional ni duración; muestra el datetime civil sin conversión silenciosa y no inventa campos.
4. No existe gestión cliente segura de una cita; requiere backend antes de diseñar acciones.
5. Metadatos dinámicos no sustituyen renderizado servidor.
6. Validación visual autenticada, zoom y lector de pantalla pertenecen a 5F.1.
