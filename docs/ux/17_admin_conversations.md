# Clientes y conversaciones del Business Admin — Sprint 5B.3

Fecha: 4 de agosto de 2026.

## Resultado

La sección `conversations` se presenta como **Clientes y mensajes**, una bandeja operativa para revisar consultas, responder por el canal realmente disponible y consultar el contexto fiable del cliente. El cambio mantiene HTML, CSS y JavaScript vanilla, todos los endpoints, el polling existente, los permisos y los contratos DOM documentados.

En escritorio la pantalla usa tres paneles independientes: lista, conversación activa e información del cliente. En tablet conserva lista y conversación y abre el cliente en un drawer. En móvil el recorrido es secuencial: lista → conversación → detalle del cliente.

## Contratos preservados

- Hash y sección: `#conversations` y `data-admin-section="conversations"`.
- Filtros: `#conversation-status-filter`, `#conversation-channel-filter` y `#conversation-search`.
- Bandeja y detalle: `#conversation-list`, `#conversation-detail`, `#conversation-thread`, `#conversation-reply-body` y `#conversation-feedback`.
- Configuración secundaria: `#conversation-templates-panel` y `#conversation-automation-panel`.
- Carga: `GET /api/admin/businesses/{slug}/conversations` y `GET /api/admin/businesses/{slug}/conversations/{id}`.
- Respuesta integrada o manual: `POST /api/admin/businesses/{slug}/conversations/{id}/messages`.
- Respuesta asistida: `POST /api/admin/businesses/{slug}/conversations/{id}/assisted-delivery`.
- Estado, automatización, sugerencias y plantillas mantienen sus rutas anteriores.

La autorización continúa en el backend. El frontend siempre construye las rutas con el `slug` de la sesión y no intenta sustituir el aislamiento por negocio.

## Jerarquía y priorización

La bandeja mantiene el máximo de 100 resultados y los filtros remotos ya existentes. Dentro de la respuesta recibida se hace una ordenación estable: primero conversaciones con `needs_reply`, después las que tienen un seguimiento Growth y después las marcadas manualmente como `pending`; dentro de cada grupo se conserva el orden reciente del backend. La búsqueda espera 350 ms después de escribir para evitar una petición por pulsación.

Cada fila muestra nombre disponible, canal, estado amable, vista previa, última actividad y recuento pendiente. Los estados internos se traducen así:

| Estado interno | Texto visible |
| --- | --- |
| `pending` | Pendiente |
| `replied` | Respondida |
| `closed` | Cerrada |

`Necesita respuesta` se deriva exclusivamente del orden del historial entre inbound y outbound válidos. `Requiere seguimiento` se deriva de una `CustomerOpportunity` pendiente del Customer asociado. Ambos estados son independientes del lifecycle `pending`/`closed` de Conversation.

## Historial y entrega

Los mensajes se ordenan cronológicamente de forma defensiva, se agrupan por día y distinguen:

- entrante del cliente;
- saliente manual;
- saliente automático;
- sistema;
- error de entrega.

Los estados de entrega se traducen sin exponer términos de cola o proveedor: `queued` es **Preparando**, `processing` es **Enviando**, `retry` es **Reintentando**, y `blocked`, `failed` o `cancelled` son **No entregado**. Se mantienen **Enviado**, **Entregado** y **Leído** cuando el proveedor los confirma.

## Matriz del compositor

El compositor usa exclusivamente las capacidades canónicas serializadas por el backend:

| Situación | Comportamiento |
| --- | --- |
| Canal manual | Registra una respuesta interna |
| `integrated_delivery_available` | Permite enviar desde AutonoGrow |
| WhatsApp sin envío integrado y `assisted_delivery_available` | Conserva el borrador y permite abrir WhatsApp; no marca el mensaje como enviado |
| Ventana de 24 h cerrada | Explica el límite y ofrece solo el flujo asistido cuando está disponible |
| Canal desconectado, suspendido o no soportado | Modo solo lectura y acceso a revisar el canal |

`instagram_provider_configured` no participa en ninguna decisión nueva. El badge usa `provider_configured`, `delivery_supported` e `integration_status`; el campo antiguo permanece únicamente como compatibilidad de API.

Los envíos manuales, integrados, asistidos y los cambios de estado se protegen contra doble activación. La URL asistida solo se abre cuando es HTTPS, pertenece exactamente a `wa.me` y no incluye credenciales. El borrador integrado se limpia solo tras éxito; el asistido nunca se limpia automáticamente.

## Contexto de cliente y reservas

El tercer panel utiliza exclusivamente la asociación persistente `Conversation.customer_id`. Al seleccionar una conversación, la ficha del Customer asociado se carga directamente; no hay una acción adicional “Ver cliente” ni heurísticas frontend basadas en reservas.

Cuando hay Customer se muestran su información y Customer Memory. Sin Customer, Admin puede asociarlo o cambiar la asociación; Staff conserva acceso de lectura sin controles muertos.

## Concurrencia, polling y estados parciales

Se conservan las tareas `conversationList` y `conversationThread`, sus intervalos, backoff y pausa por visibilidad. `conversationLoadVersion` y `conversationDetailVersion` descartan respuestas antiguas; los fingerprints evitan renders sin cambios. El estado capturado conserva borrador, selección, scroll, cercanía al final e indicador de mensajes nuevos.

Un fallo de sugerencias ya no oculta el historial: se muestra un aviso parcial y la conversación sigue utilizable. Los errores de lista y detalle ofrecen reintento y no serializan objetos técnicos del backend. No se añadió WebSocket, `setInterval` ni un segundo pipeline de refresco.

## Responsive y accesibilidad

- Desktop, desde 1200 px: tres paneles con scroll independiente.
- Tablet, hasta 1199 px: dos paneles y drawer de cliente con backdrop.
- Móvil, hasta 639 px: lista o detalle, nunca ambos comprimidos; el compositor respeta `safe-area-inset-bottom`.
- La lista usa `role="listbox"`, selección con `aria-selected`, estados de carga con `aria-busy` y feedback `aria-live`.
- El drawer devuelve el foco al disparador, se cierra con Escape y mantiene el foco con Tab/Shift+Tab.
- El botón de volver devuelve el foco a la conversación seleccionada.
- Las transiciones se eliminan con `prefers-reduced-motion`.

## Verificación

La cobertura estática específica vive en `backend/tests/test_admin_conversations_ui.py`. Comprueba arquitectura e IDs, priorización, debounce, traducciones, agrupación, matriz del compositor, ausencia del campo legado en decisiones, URL segura, doble envío, reutilización de reservas, responsive, foco, polling, versionado, escape de contenido y errores parciales.

La validación visual reproducible requiere servidor local, sesión Business Admin y datos representativos de los tres canales. Debe revisarse a 360, 390, 768, 1024 y 1440 px, con teclado y zoom al 200 %. En el entorno de implementación no se asumió autenticación ni se añadieron datos de prueba al backend para fabricar capturas.
