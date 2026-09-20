# Modo focalizado de conversaciones

Fecha: 20 de septiembre de 2026.

## Auditoría de la arquitectura anterior

La sección `#conversations` mantenía en el DOM un `conversation-center` con tres hijos permanentes: `conversation-list-panel`, `conversation-detail` y `conversation-customer-panel`. En escritorio amplio, CSS los distribuía como lista + hilo + ficha de cliente; entre 640 y 1599 px conservaba lista + hilo y transformaba la ficha en drawer; solo por debajo de 640 px alternaba lista y detalle mediante `conversation-mobile-detail-open`.

El estado se concentraba en `selectedConversationId`, `selectedConversation`, las sugerencias, el estado del drawer y los borradores/scroll capturados por `captureConversationUiState`. `loadConversations` elegía automáticamente la primera conversación. `selectConversation` cargaba detalle y sugerencias y `conversationDetailVersion` descartaba respuestas tardías. El compositor, Plantillas y Automatización se renderizaban dentro del footer. La ficha de cliente conservaba Customer Memory, Growth y asociación. La URL solo reflejaba `#conversations`; no identificaba la conversación seleccionada.

## Arquitectura final

Hay dos estados excluyentes en todos los viewports:

1. Bandeja: cabecera, resumen, búsqueda, filtros y lista completa de tarjetas de triage.
2. Workspace focalizado: cabecera compacta, historial con scroll propio, compositor y herramientas secundarias bajo demanda.

`conversation-focus-mode` oculta los controles globales de bandeja y `conversation-focus-open` sustituye visualmente la lista por el detalle. No se abre otra pestaña ni se crea una arquitectura distinta para tablet. La lista ya no selecciona la primera conversación automáticamente.

Las tarjetas conservan nombre o identificador fiable, identidad de canal (usuario o teléfono), canal, asociación, estados `needs_reply`, seguimiento Growth y pendiente manual, preview, fecha y recuento pendiente. Customer Memory no se duplica en la bandeja.

## Navegación e historial

El deep link mínimo amplía el router actual con `?conversation=<id>#conversations`.

- Un click desde bandeja usa `pushState` una sola vez.
- El botón **Conversaciones** usa la entrada anterior cuando fue creada por el workspace; en un deep link directo limpia el parámetro con `replaceState` y vuelve a un estado seguro.
- `popstate` reconcilia sección y conversación sin generar nuevas entradas: Back muestra la bandeja y Forward vuelve a cargar el workspace.
- Un acceso desde Growth crea directamente la entrada focalizada, de modo que Back recupera el contexto Growth sin una parada intermedia artificial.
- Una conversación inexistente o no autorizada limpia el deep link y conserva la bandeja con feedback recuperable.

Al cerrar el workspace se incrementa `conversationDetailVersion`, se limpia la selección y se restaura el foco a la tarjeta desde la que se abrió. Así, una respuesta tardía de A no puede repoblar el DOM después de volver y abrir B. El polling, el control de generación de sesión y los endpoints existentes no cambian.

## Workspace y contexto secundario

La cabecera tiene dos líneas: nombre y acciones operativas en la primera; identidad mínima y asociación en la segunda. Canal, estado de integración, intención, confianza y estados de atención viven en **Información del cliente**. ADMIN y STAFF comparten estructura; los controles de mutación continúan gobernados por los permisos existentes.

El historial ocupa la fila flexible `minmax(0, 1fr)` y tiene scroll propio. El compositor permanece en el footer. En móvil, la altura útil descuenta `--ag-topbar-min-height`, `--ag-mobile-nav-height`, padding y `safe-area-inset-bottom`, evitando que la navegación inferior tape el composer.

Plantillas y Automatización son botones compactos que abren un overlay dentro del workspace. Comparten un sheet amplio, con scroll propio, backdrop, Escape, contención y restauración de foco. Seleccionar una plantilla cierra el sheet, conserva la conversación y lleva el texto editable al composer. Automatización conserva sus controles, sugerencias, permisos y lógica de negocio sin ocupar altura cuando está cerrada.

Información del cliente es siempre un drawer modal bajo demanda, también en desktop. Conserva asociación, Customer Memory, visitas/contexto disponible, Growth y todas sus acciones. Tiene backdrop, cierre con Escape, contención de foco, devolución de foco y scroll independiente; en móvil termina por encima de la navegación fija.

## Semántica de cierre

**Cerrar** mantiene su significado de lifecycle de Conversation y no abandona automáticamente el workspace. No resuelve Growth, no modifica Customer Memory y no altera identidad, asociación ni permisos. Volver a bandeja es una acción de navegación separada y explícita.

## Contratos preservados

- IDs DOM de lista, detalle, hilo, compositor, filtros, feedback, lanzadores de Plantillas/Automatización y ficha de cliente.
- Endpoints y payloads de conversación, mensajes, estado, asociación, automatización, sugerencias, plantillas y Customer Memory.
- Aislamiento por `business slug`, autorización backend y visibilidad ADMIN/STAFF.
- `conversationLoadVersion`, `conversationDetailVersion`, fingerprints, polling único, borrador y posición del hilo.
- `needs_reply`, `manual_pending`, seguimiento Growth y backlinks.
