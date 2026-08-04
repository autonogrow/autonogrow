# Reseñas y crecimiento del Business Admin — Sprint 5B.6

Fecha: 4 de agosto de 2026.

## Resultado y arquitectura

La antigua pantalla de Crecimiento mezclaba una lista diaria calculada en cliente, puntos, celebraciones persistidas en `localStorage` y recomendaciones estáticas. Reseñas era otra pestaña primaria, aunque dependía de reservas y del outbox. La nueva familia conserva los contratos heredados y agrupa la operación así:

```text
Crecimiento
├── Resumen
├── Reseñas
└── Oportunidades
```

El Resumen responde con datos operativos; Reseñas separa clientes atendidos, solicitudes que necesitan seguimiento e historial; Oportunidades explica condiciones reales y su dependencia. La pestaña primaria heredada `reviews`, sus contenedores, IDs y endpoints permanecen, pero la navegación principal entra por Crecimiento.

No se modificó backend funcional, modelos, migraciones, permisos, payloads ni endpoints. Tampoco se añadieron campañas, analítica de reputación, scraping, una API de Google Business Profile o automatización de reseñas.

## Fuentes reales

| Información | Fuente | Interpretación visible |
| --- | --- | --- |
| Clientes pendientes de solicitud | Reservas `completed` sin `ReviewRequest` conocida | Cliente atendido; todavía no equivale a una solicitud |
| Solicitudes preparadas | `ReviewRequest.status` en `pending` o `copied` | Requieren envío o decisión humana |
| Marcadas como enviadas | `ReviewRequest.status == sent` | Declaración manual; no prueba entrega ni reseña publicada |
| Solicitudes con error | `MessageOutbox.message_type == booking_completed_review` y `status == failed` | El mensaje asistido no quedó preparado correctamente |
| Actividad | Fechas fiables de `ReviewRequest` y outbox de reseña | Preparada, copiada, abierta, marcada como enviada, omitida o fallida |
| Reservas y mensajes pendientes | Loaders existentes de Agenda y Conversaciones | Condiciones accionables |
| Servicios, horarios, publicación y galería | Estado ya cargado por Configuración | Bloqueos o recomendaciones comprobables |
| Reconexión de canal | Diagnóstico seguro de canales | Bloqueo concreto de Instagram o WhatsApp |

No se calculan conversión, ingresos, ROI, posición, puntuación media, reseñas conseguidas ni impacto estimado.

## Matriz de acciones

| Acción | Fuente real | Business Admin | Dependencias | Resultado |
| --- | --- | --- | --- | --- |
| Consultar oportunidades | Estado ya cargado de reservas, conversaciones y configuración | Sí | Carga parcial de cada fuente | Lista ordenada sin persistencia local |
| Abrir reserva | Reserva del negocio presente en `allBookings` | Sí | ID interno usado solo para navegación | Agenda conserva contexto y enfoca la tarjeta |
| Abrir cliente | No existe destino estable desde una solicitud de reseña | No se ofrece | Requeriría una relación o endpoint no existente | No se inventa acción |
| Solicitar reseña | POST de review request existente | Sí | Reserva completada y enlace válido | Solicitud idempotente y mensaje asistido |
| Volver a intentar solicitud fallida | No existe endpoint específico seguro | No se ofrece | Backend tendría que definir semántica | Se explica el bloqueo sin reintento local |
| Abrir mensaje asistido | POST idempotente + PATCH `opened` del outbox | Sí | Teléfono y URL `wa.me` válidos; popup permitido | WhatsApp se abre; no se marca como enviado |
| Descartar recomendación | No existe persistencia backend | No se ofrece | Endpoint de descarte inexistente | La condición desaparece solo si cambia el dato real |
| Marcar tarea completada | Derivada de la condición | No existe acción manual | El backend o dato real debe cambiar | La oportunidad se resuelve al dejar de cumplirse |
| Configurar enlace de reseñas | Formulario y PATCH existentes de negocio | Sí | Permiso Business Admin | Navega a Configuración / Información y enfoca el campo |

## Resumen y priorización

Las cinco métricas son clientes pendientes, solicitudes preparadas, marcadas como enviadas, solicitudes con error y oportunidades activas. Se mantiene la barra DOM heredada, ahora descrita como condiciones operativas resueltas y sin puntos.

La prioridad visible es: bloqueos de operación, solicitudes preparadas, fallos conocidos, clientes elegibles y después recomendaciones. Cada tarjeta indica qué ocurre, por qué importa, dependencia y destino. Los estados `neutral` de fuentes aún cargando no se contabilizan como oportunidad ni como condición completada.

El Dashboard muestra como máximo una alerta de reseñas equivalente: primero fallo, después enlace bloqueante y después solicitudes o clientes pendientes. No afirma que una solicitud sea una reseña obtenida.

## Elegibilidad

La lógica disponible en el producto es deliberadamente estrecha:

1. la reserva pertenece al negocio resuelto por la ruta autenticada;
2. su estado es `completed`;
3. no existe una solicitud previa para esa reserva;
4. el negocio tiene un enlace de reseñas no vacío; el frontend, además, exige el protocolo público seguro admitido;
5. el permiso Business Admin se valida en servidor.

La restricción única por `booking_id` y `get_or_create_review_request` preservan idempotencia. Un teléfono válido habilita WhatsApp asistido; si falta, todavía puede prepararse y copiarse el mensaje. El backend actual no define espera mínima tras la cita, seguimiento de reseña publicada, bloqueo por créditos ni automatización específica. La interfaz no añade esas reglas.

Cada tarjeta muestra cliente, servicio, fecha, estado, canal disponible y acción. No muestra booking ID, customer ID, review request ID ni outbox ID. Los identificadores permanecen únicamente como referencias internas necesarias para las rutas autorizadas.

## Flujo de solicitud y entrega asistida

Antes de preparar se confirma cliente, canal, tipo de entrega, enlace y resultado esperado. El POST existente devuelve la solicitud y su mensaje de outbox. La interfaz sustituye el estado canónico, actualiza Agenda, Reseñas, actividad, Resumen, Dashboard y solicita el refresh operativo existente.

Para WhatsApp se abre primero una pestaña vacía como consecuencia directa del gesto del usuario. Se valida `wa.me` antes y después del PATCH `opened`; la pestaña pierde `opener`. Solo entonces navega a la URL devuelta por el servidor. `opened` significa que WhatsApp se abrió, no que el mensaje se enviara. “Marcar como enviada” exige confirmación humana y tampoco significa entrega o reseña publicada.

## Envío integrado, automatización y créditos

Las solicitudes de reseña actuales no entran en el worker multicanal ni disponen de modo integrado. Su outbox es el legado asistido con enlace `wa.me`. Por ello Crecimiento no muestra capacidad integrada, ventana de 24 horas ni saldo de créditos: ninguno determina esta acción.

Las automatizaciones existentes son respuestas de conversación y no incluyen una regla de solicitud de reseña. La pantalla lo dice de forma explícita y solo enlaza al editor existente; no duplica reglas ni activa nada. El estado integrado, la ventana de WhatsApp, permisos de canal y créditos siguen intactos en **Canales y automatizaciones**, donde sí son relevantes.

## Estados, errores y reintentos

`ReviewRequest` solo usa `pending`, `copied`, `sent` y `skipped`. El outbox asistido solo usa `pending`, `opened`, `sent`, `skipped` y `failed`. La vista los combina sin inventar `queued`, `delivered`, `cancelled`, `assisted` o `review_received`:

- solicitud preparada;
- mensaje copiado;
- abierta en WhatsApp;
- marcada como enviada;
- omitida;
- no se pudo preparar.

Los errores visibles son genéricos y accionables. No incluyen detalles backend, Graph API, traceback, payload, token, job ni IDs. No hay botón de reintento para un outbox fallido porque el backend no ofrece una operación específica segura. Copiar, crear, abrir o cambiar estado bloquea mutaciones repetidas; las respuestas obsoletas de solicitudes y outbox se descartan con versiones de carga.

Los fallos son parciales: un error de outbox conserva los clientes cargados; un error de solicitudes conserva el snapshot anterior; un error de oportunidades no sustituye el contenido de Reseñas. Un estado vacío positivo solo aparece cuando las fuentes requeridas han terminado y no hay error conocido.

## Enlace de reseñas

La única fuente de verdad es `currentBusiness.reviews_url`, editada por el formulario existente de Configuración / Información. Crecimiento distingue configurado, ausente y configurado pero no válido. Valida con el helper de URL pública actual, escapa el atributo, añade `noopener noreferrer` y no genera, acorta ni modifica URLs.

## Oportunidades y actividad

Las oportunidades posibles derivan de: enlace ausente, solicitudes preparadas o fallidas, clientes atendidos, reservas pendientes, conversaciones sin responder, ausencia de servicio activo, horarios vacíos, negocio inactivo, galería vacía y reconexión de un canal concreto. No se pueden descartar o completar manualmente; reaparecen mientras la condición real exista.

Actividad reciente se limita a seis cambios relacionados con solicitudes y usa únicamente timestamps existentes. No presenta auditoría técnica, logs ni supuestas reseñas recibidas.

## Integración con otras áreas

- **Dashboard:** añade una alerta real y no duplicada de reseñas cuando las fuentes están disponibles. Tras cada mutación se recalcula.
- **Agenda:** una reserva completada conserva un único flujo: puede preparar la misma solicitud o abrir su gestión en Crecimiento. No existe una segunda fuente de estado.
- **Conversaciones / outbox:** el mensaje sigue en el outbox asistido con su tipo y cliente. Abrir WhatsApp no lo presenta como enviado y el servicio impide duplicados por negocio, reserva y tipo.

## Polling y concurrencia

No se añadió intervalo. La tarea `operations` existente carga reservas, review requests y outbox. La subsección, hash, filtros, scroll y formularios sucios no se reinician. Los fingerprints evitan renders innecesarios cuando no cambia la colección; las versiones descartan respuestas antiguas y los conjuntos de mutación bloquean dobles acciones.

## Responsive y accesibilidad

En escritorio hay navegación secundaria fija y contenido legible. A 1023 px pasa a navegación horizontal de tres categorías; a 639 px usa una columna, acciones de ancho completo, objetivos táctiles y espacio inferior con safe area. No hay tablas ni overflow horizontal requerido. Se cubren estructuralmente 360, 390, 768, 1024 y 1440 px.

La página conserva un único `h1`, jerarquía `h2`/`h3`, botones nativos, `aria-current`, nombres de navegación, estados textuales, `aria-busy` por bloque, errores con `role=alert`, feedback moderado y foco visible heredado. Las confirmaciones son nativas y no requieren un segundo focus trap. `prefers-reduced-motion` elimina transiciones y animaciones relevantes.

## Seguridad

Todas las rutas incluyen el slug actual y el servidor vuelve a resolver negocio, membresía y reserva. El frontend no puede autorizar acceso entre tenants. Nombre, servicio, mensaje, estado y URL se escapan antes de interpolarse; las URLs públicas y `wa.me` se validan; las aperturas externas usan `noopener`; los errores se redactan; no se muestra el ID de reserva en tarjetas ni outbox.

Los botones se deshabilitan durante mutaciones, se comprueba el snapshot local antes de crear y el backend mantiene idempotencia. No se alteraron permisos, auditoría ni aislamiento existentes.

## Pruebas y validación manual

`backend/tests/test_admin_growth_reviews.py` cubre arquitectura, contratos, fuentes, elegibilidad, idempotencia, tenant, entrega asistida, estados, enlace, errores, navegación, oportunidades, polling, integración y estructura responsive/accesible. También se mantienen las suites focales de shell, polling, Dashboard, Agenda, Conversaciones, Configuración y Canales.

No había sesión autenticada ni escenarios reproducibles proporcionados para capturas, y no se fabricaron datos ni se alteró la base. Validación manual pendiente:

1. 1440 × 900: Resumen, clientes, solicitudes y oportunidades;
2. 1024 × 768: canal con reconexión requerida;
3. 768 × 1024: Reseñas con solicitud pendiente;
4. 390 × 844: Resumen y apertura asistida;
5. 360 × 800: vacíos y error parcial;
6. teclado, zoom 200/400 % y NVDA o VoiceOver.

## Limitaciones deliberadas

- No existe seguimiento de reseña publicada, puntuación o plataforma externa.
- No existe entrega integrada ni automatización específica de solicitudes.
- No existe reintento dedicado de outbox fallido ni descarte persistente de oportunidades.
- No existe enlace directo fiable desde una solicitud a una ficha de cliente.
- Los estados `sent` de solicitud y outbox se mantienen según sus contratos heredados independientes.
