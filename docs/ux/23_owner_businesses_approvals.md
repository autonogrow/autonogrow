# Negocios, altas y aprobaciones del panel Owner — Sprint 5C.2

Fecha: 5 de agosto de 2026. Rama: `main`. Base inicial: `738422c`.

## Alcance y estructura anterior

Antes de 5C.2, `Negocios` renderizaba una tarjeta extensa por cuenta y cargaba de inmediato galería, usuarios, controles de canal, Instagram y automatización. Las acciones críticas convivían con el resumen; no había búsqueda ni filtros. `Nuevo negocio` solo contenía el wizard de alta. Las candidaturas se revisaban dentro de detalles técnicos dispersos y el Dashboard llevaba a la tarjeta completa.

El sprint reorganiza exclusivamente `Negocios` y `Altas y aprobaciones`. Resumen, Incidencias, Colas/worker y Operaciones mantienen comportamiento y contratos. Integraciones y Auditoría no reciben páginas vacías ni un rediseño de 5C.3. No se modifican backend funcional, modelos, migraciones, endpoints, payloads, permisos, Business Admin ni landings.

## Arquitectura final

```text
Owner
├── Resumen
├── Negocios
│   ├── directorio, búsqueda y filtros
│   └── detalle
│       ├── Resumen
│       ├── Datos y marca
│       ├── Usuarios y acceso
│       ├── Activación
│       ├── Canales
│       └── Actividad disponible
├── Altas y aprobaciones
│   ├── Altas en curso
│   ├── onboarding existente
│   └── Decisiones pendientes
│       ├── Instagram
│       └── WhatsApp
├── Incidencias (heredado)
└── Operaciones/colas (heredado)
```

El detalle se abre desde la lista sin perder búsqueda ni filtro. La navegación secundaria cambia de bloque sin recargar la lista. Los accesos contextuales desde Resumen llevan una candidatura a su revisión exacta, un negocio al detalle y una integración degradada al bloque Canales.

## Fuentes y datos seguros

| Fuente | Endpoint existente | Datos mostrados | Datos omitidos |
|---|---|---|---|
| Negocios | `GET /api/owner/businesses` | nombre, slug, ciudad, estado, fechas, salud básica, métricas | IDs como texto, payloads internos |
| Accesos | `GET /api/owner/businesses/{slug}/users` | nombre, email, rol, activo, vinculación, asignación | `user_id`, `membership_id`, permisos Owner |
| Onboarding | `GET /api/owner/businesses/{id}/onboarding` | paso, estados de pasos, completados, última actividad | IDs y versión técnica |
| Readiness | `GET /api/owner/businesses/{id}/readiness` | etiqueta, estado, mensaje, remediación y paso relacionado | versión visible, claves internas, SQL |
| Preview | `GET /api/owner/businesses/{id}/preview` | identidad segura y garantías `noindex`/reservas desactivadas | publicación, mutación, URL inventada |
| Controles | `GET /api/owner/businesses/{id}/channel-controls` | aprobación comercial y capacidades por separado | secretos y configuración de proveedor |
| Salud | `GET /api/owner/businesses/{id}/channels/health` | estado amigable y comprobación conocida | respuestas Meta, metadata, tokens |
| Instagram | candidatos OAuth e integración existente | nombre público, tipo, fechas, webhook, existencia previa | account ID, scopes crudos, token, state, App ID |
| WhatsApp | candidatos Embedded Signup | nombre público o teléfono redactado, fecha, setup conocido | WABA ID, phone number ID, token, PIN, payload |
| Incidencias | `GET /api/owner/incidents` | recuento abierto por negocio | cuerpo técnico en el directorio |

No existe un endpoint Owner de lectura de auditoría. `Actividad disponible` muestra únicamente hitos derivados de `created_at`, asignaciones y fechas de controles ya expuestas, y advierte que no sustituye Auditoría.

## Matriz de acciones

| Acción | Estado inicial | Resultado del backend | Confirmación | Actor |
|---|---|---|---|---|
| Crear alta | sin negocio | negocio y sesión de onboarding | formulario de alta | Owner |
| Continuar onboarding | alta existente | abre sesión y paso real | no crítica | Owner |
| Revisar readiness | configuración existente | evaluación versionada | no crítica | Owner |
| Previsualizar | no archivado | preview privada, noindex y reservas desactivadas | no crítica | Owner |
| Activar | onboarding/configuración, readiness válido | `active` | diálogo con motivo y versión esperada | Owner |
| Suspender | `active` | `suspended` | diálogo contextual con motivo | Owner |
| Reactivar | `suspended`, readiness aún válido | `active` | diálogo contextual con motivo | Owner |
| Asignar usuario | email y rol de negocio | membresía activa | diálogo con usuario, negocio, rol y efecto | Owner |
| Cambiar rol | membresía activa | rol actualizado | diálogo actual/nuevo; último admin protegido en UI | Owner |
| Desactivar acceso | membresía activa | acceso inactivo | diálogo; último admin protegido en UI | Owner |
| Abrir Business Admin | negocio conocido | navegación segura con slug codificado | no crítica | Owner |
| Aprobar candidata Instagram | `candidate_ready` | promoción/reemplazo seguro | diálogo con conexión anterior y capacidades | Owner |
| Rechazar candidata Instagram | `candidate_ready` | candidata rechazada | diálogo con motivo; anterior conservada | Owner |
| Aprobar candidata WhatsApp | `candidate_ready` | promoción/reemplazo seguro | diálogo con conexión anterior y capacidades | Owner |
| Rechazar candidata WhatsApp | `candidate_ready` | candidata rechazada | diálogo con motivo; anterior conservada | Owner |
| Revisar sustitución | candidatura de reemplazo | solo lectura hasta decidir | explicación explícita | Owner |

La API actual de usuarios no rechaza por sí sola desactivar o degradar al último administrador. Para respetar la restricción de no cambiar backend, 5C.2 bloquea ambas acciones en la interfaz con los accesos cargados y obliga a asignar otro administrador primero. Añadir la misma garantía transaccional al backend queda como deuda de defensa en profundidad.

## Directorio, filtros y orden

La fila compacta muestra nombre, slug/ciudad, estado real, fase de alta separada, administrador, canales, incidencias, hasta dos alertas, creación y accesos seguros. Suspender, revocar o aprobar no aparecen en la fila.

La búsqueda es local por nombre, slug, ciudad y email administrativo ya descargado. Los filtros fiables son Todos, Activos, Onboarding, Pendientes (`draft`, `configuration_pending`, `ready`), Suspendidos, Necesitan atención y Sin administrador. Si usuarios falla, el negocio no se clasifica como “sin administrador”. El orden es: decisión/atención, onboarding incompleto, suspendidos, activos y resto; dentro de cada grupo se ordena por nombre.

## Detalle, datos y marca

Resumen separa estado comercial, fase de alta, publicación, administrador, servicios, horarios, canales e incidencias. Datos y marca reutiliza paleta, plantilla, logo y galería existentes; nombre, contacto, dirección y contenido se leen de la fuente Owner y el enlace contextual abre el editor canónico de Business Admin. No se duplica la fuente de verdad ni se rediseña la landing.

Canales reutiliza controles, salud, Instagram y plan heredados. Se retiraron de esa presentación scopes crudos, IDs de cuenta y formularios manuales de token. OAuth sigue siendo el acceso seguro. Candidatura, integración activa, control comercial, capacidades y salud conservan etiquetas y bloques separados.

## Usuarios y roles

El editor solo ofrece `business_admin` y `business_staff`; nunca `owner` ni roles inventados. Cada fila muestra identidad, email, rol, acceso, vinculación y fecha si existe. Asignación, cambio de rol, desactivación y reactivación usan el diálogo crítico. La operación siempre usa el slug seleccionado y el identificador interno solo viaja en el atributo/petición, nunca como texto.

## Altas, onboarding, readiness y preview

Altas en curso consulta la sesión real por negocio pendiente. El progreso es la unión de pasos completados y omitidos respecto al conjunto de pasos devuelto: “N de M pasos”, sin porcentaje inventado. Muestra paso actual, bloqueo de readiness, última actividad y errores aislados por alta.

El wizard existente conserva sus quince pasos, endpoints, navegación, guardado y estados. Readiness mapea `passed` a Correcto, `warning` a Recomendado y comprobaciones bloqueantes a Bloqueante, mostrando mensaje, remediación y destino del paso. La versión solo se usa al activar. Preview no publica: presenta explícitamente `noindex`, reservas desactivadas, automatizaciones desactivadas y ausencia de consumo de créditos, con vuelta a onboarding y readiness.

## Candidaturas y reemplazo seguro

El hub reúne únicamente decisiones reales de candidaturas `candidate_ready`, sin mezclarlas con incidencias o salud. Instagram y WhatsApp se renderizan desde fuentes independientes por negocio. La revisión muestra negocio, nombre público seguro, fecha, existencia de integración anterior, control comercial y salud conocida.

Cuando consta conexión anterior, el flujo explica que seguirá funcionando hasta que el servidor confirme la nueva. Aprobar usa el endpoint existente de decisión, no habilita envío o automatización y espera la respuesta antes de cerrar. Rechazar solicita motivo y explica que no revoca la integración anterior. No se pide PIN, token ni registro manual; no se muestran IDs técnicos, scopes, state, metadata ni respuestas de proveedor.

## Acciones críticas, concurrencia y errores parciales

Un único diálogo `role="dialog"` presenta recurso, estado actual, resultado, consecuencia y motivo. Atrapa foco, admite Escape/cancelación, devuelve foco y deshabilita todos sus controles durante la mutación. No hay actualización optimista: permanece abierto hasta respuesta backend; luego refresca Dashboard, directorio y detalle. Una segunda acción no puede abrirse mientras el diálogo está activo.

Usuarios, onboarding, readiness, candidatos, integración anterior, canales e incidencias tienen errores independientes. Un fallo de WhatsApp no oculta Instagram; un fallo de usuarios no borra readiness; una fuente fallida nunca se presenta como cola vacía. No se añadieron intervalos: la actualización es manual y las fuentes se refrescan después de mutaciones.

## Responsive y accesibilidad

La lista de cinco columnas pasa a dos bajo 1200 px y a tarjetas de una columna bajo 768 px. Filtros, capas de candidatura, resumen, acciones y diálogo se apilan; no hay tablas ni overflow global. El diálogo respeta `100dvh`, safe areas y botones de ancho completo en móvil. La navegación secundaria permite scroll horizontal local.

Se conservan `h1`, landmarks, skip link, botones nativos, labels y `aria-current`. Lista y filas tienen semántica de lista, cada bloque usa `aria-busy`, los errores críticos usan `role="alert"`, el diálogo gestiona foco/Escape/retorno y `prefers-reduced-motion` evita desplazamiento animado.

## Seguridad y rendimiento

Todos los valores dinámicos pasan por `escapeHtml`; slugs e identificadores usados en rutas pasan por `encodeURIComponent`. Los enlaces internos solo usan rutas conocidas y `rel="noopener"`. Los errores de mutación se traducen por estado HTTP y no reproducen cuerpos o excepciones del backend. No se registran respuestas ni secretos.

La lista usa los negocios ya cargados y búsqueda/orden local. Usuarios y altas se cargan en lotes de cuatro; el detalle solo carga galería, usuarios, readiness o canales al abrir su subsección. No hay polling nuevo, recarga completa ni un segundo sistema de onboarding.

## Pruebas y validación pendiente

`backend/tests/test_owner_businesses_approvals.py` cubre arquitectura, contratos DOM, filtros, orden, estados, seguridad, diálogo, navegación contextual, fuentes y ausencia de backend nuevo. También se ejecutan shell, Dashboard, suites Owner/onboarding/candidaturas/canales/auditoría, Ruff, `git diff --check` y la suite completa.

Por decisión del sprint quedan para QA final las comprobaciones autenticadas, E2E, zoom y lector de pantalla, y estas vistas: 1440×900 lista/detalle/usuarios/readiness/Instagram/WhatsApp; 1024×768 onboarding; 768×1024 detalle; 390×844 lista/aprobación; 360×800 diálogo o error. No se alteró la base ni se fabricaron capturas.

## Limitaciones y deuda

- Protección transaccional backend del último administrador, sin abordarla aquí por la prohibición de backend funcional.
- Auditoría consultable cuando exista un contrato de lectura; no se inventa en 5C.2.
- QA visual autenticado, E2E, zoom y lector de pantalla en el cierre transversal.
- Rediseño técnico completo de Integraciones reservado a 5C.3.
