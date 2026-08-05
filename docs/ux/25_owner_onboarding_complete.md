# Onboarding completo de negocio en Owner

## Estado y estructura anterior

Sprint 5D.1 parte de `main` en `43013c3`, con el árbol limpio. El flujo heredado ya llamaba al backend real, pero presentaba formularios mínimos, avanzaba localmente en algunos casos, no separaba guardado y navegación, no avisaba de cambios sin guardar y mezclaba el paso de personal con la idea de acceso. Readiness y preview existían como acciones aisladas, sin una revisión final agrupada ni un resultado operativo tras activar.

No se ha modificado backend funcional, autenticación, permisos, modelos, migraciones, endpoints ni el orden de pasos. Tampoco se ha iniciado 5E.1.

## Arquitectura final

El flujo permanece dentro de `Altas y aprobaciones` y se implementa como mejora progresiva en `owner-onboarding.js`, cargado después de `owner.js`, `owner-businesses.js` y `owner-operations.js`.

Tras la revisión previa al commit, `owner.js` conserva únicamente `onboardingData`, `onboardingStepIndex` y `onboardingReadiness` como estado compartido, además del hook de carga inicial. La definición de pasos, apertura, formularios, payloads, readiness, preview, activación y todos los listeners del wizard pertenecen exclusivamente a `owner-onboarding.js`; `owner-businesses.js` consume sus etiquetas y función de apertura sin mantener una segunda implementación.

```text
Nueva alta
└── creación mínima y segura
    └── shell del negocio
        ├── identidad: plantilla, identidad, contacto
        ├── operación: servicios, equipo, automatizaciones
        ├── disponibilidad: horario y reglas de reserva
        ├── página pública: marca y contenido
        ├── canales y plan
        └── cierre: revisión/readiness, preview y activación
```

La agrupación es exclusivamente visual. Las 15 claves, su orden, estado y guardado independiente siguen siendo los del servidor.

## Fuentes

- Sesión, negocio, servicios, perfiles, disponibilidad parcial e integraciones: `GET /api/owner/businesses/{id}/onboarding`.
- Plantillas: `GET /api/owner/onboarding/templates`.
- Creación: `POST /api/owner/businesses/onboarding`.
- Configuración de cada paso: endpoints existentes bajo `/api/owner/businesses/{id}/onboarding/*`.
- Readiness y su versión: `GET /api/owner/businesses/{id}/readiness`.
- Preview privada: `GET /api/owner/businesses/{id}/preview`.
- Activación: `POST /api/owner/businesses/{id}/activate`.
- Reglas ampliadas y excepciones: fuentes Admin existentes de availability.
- Automatizaciones, créditos, accesos y capas de canal: fuentes Owner ya usadas en 5C.1–5C.3.

El frontend no reconstruye readiness, no obtiene la identidad de la persona iniciadora —la respuesta solo expone identificadores internos, que no se muestran— y no interpreta una fuente fallida como un valor negativo o correcto.

## Matriz de pasos

| # | Clave real | Presentación | Método y ruta existente | Obligatorio para completar |
|---:|---|---|---|---|
| 1 | `template` | Plantilla | `POST …/onboarding/template` | plantilla válida |
| 2 | `business_identity` | Identidad | `PUT …/onboarding/identity` | nombre y slug válidos |
| 3 | `contact_and_location` | Contacto y ubicación | `PUT …/onboarding/contact` | el backend decide según contacto público |
| 4 | `services` | Servicios | `PUT …/onboarding/services` | al menos uno activo y reservable |
| 5 | `staff` | Equipo | `PUT …/onboarding/staff` | al menos un perfil activo para completar el paso |
| 6 | `schedules` | Horario habitual | `PUT …/onboarding/schedules` | al menos un día abierto |
| 7 | `booking_rules` | Reglas de reserva | `PUT …/onboarding/booking` | payload coherente y válido |
| 8 | `branding` | Marca | `PUT …/onboarding/branding` | color principal o logo según backend |
| 9 | `landing_content` | Contenido público | `PUT …/onboarding/landing` | titular y descripción |
| 10 | `automations` | Automatizaciones | `PUT …/onboarding/automations` | guardado válido; no implica habilitación |
| 11 | `integrations` | Canales | `POST …/onboarding/steps/integrations/skip` | opcional; se registra omisión explícita |
| 12 | `credits_and_plan` | Plan y créditos | `PUT …/onboarding/credits` | inicialización válida e idempotente |
| 13 | `readiness_review` | Revisión y readiness | `GET …/readiness` | solo queda completo si readiness está listo |
| 14 | `preview` | Vista previa | `GET …/preview` | respuesta segura del backend |
| 15 | `activation` | Activación | `POST …/activate` | readiness vigente, sin bloqueos y motivo |

La creación inicial usa `POST /api/owner/businesses/onboarding` con nombre, slug opcional y plantilla/version opcionales. No crea usuarios ni integraciones desde frontend.

## Matriz de estados

| Estado real | Texto | Significado | Acción disponible |
|---|---|---|---|
| `pending` | No iniciado | el servidor aún no confirma trabajo | abrir o completar requisitos |
| `in_progress` | En curso | existe progreso sin cierre del paso | revisar y guardar |
| `completed` | Completado | backend confirmó el paso | consultar o volver a editar si el negocio no está activo |
| `skipped` | Omitido | omisión explícita permitida por backend | consultar; completar después en destino canónico |
| `blocked` | Bloqueado | faltan dependencias o readiness | ir al paso relacionado y corregir |

Además, la interfaz distingue `loading`, `ready`, `empty`, `saving`, `saved`, `error` y `conflict` como estados de presentación. Ninguno altera el progreso real.

## Entrada, creación y shell

Se entra desde Nueva alta, Altas en curso, la acción Continuar alta de Negocios o una alta pendiente/bloqueada del Dashboard. Cada entrada transmite el negocio seleccionado; nunca se abre el primero de la lista. Una promesa única evita cargas simultáneas de la misma apertura y los filtros de los hubs no se reinician.

La creación valida nombre y patrón de slug, explica su uso, bloquea el botón durante la petición y conserva el formulario si falla. El negocio devuelto abre su propia sesión y actualiza Dashboard, Negocios y Altas. Un conflicto se expresa sin copiar el detalle backend.

El shell muestra nombre, estado comercial, paso actual, progreso confirmado, último timestamp real de actividad y la limitación de la identidad iniciadora. En escritorio conserva la lista lateral agrupada; en tablet/móvil usa un selector compacto con paso, estado y controles anterior/siguiente.

## Progreso, guardado y navegación

El progreso cuenta únicamente `completed` y `skipped` de `session.steps`. Abrir o modificar un paso no cambia ese recuento.

Cada paso editable tiene Guardar y Guardar y continuar. El flujo valida HTML y reglas específicas, bloquea dobles envíos, espera la respuesta, vuelve a cargar la sesión y solo entonces actualiza progreso y timestamp. No hay autosave. Toda edición invalida readiness y preview en memoria.

Anterior, Siguiente, selector, lista y Volver a Altas pasan por una confirmación si hay cambios: Guardar y salir, Salir sin guardar o Cancelar. El diálogo atrapa foco, admite Escape y devuelve el foco. `beforeunload` cubre el cierre del navegador. No se usa `localStorage`.

## Identidad, servicios, equipo y accesos

Identidad separa nombre/slug/categoría/descripción pública de razón social e identificación fiscal internas; contacto agrupa teléfonos, email, dirección y enlaces. El slug activo exige la confirmación soportada por el payload.

Servicios permite añadir, editar, ordenar y desactivar con nombre, descripción, duración, precio, moneda, visibilidad y reserva reales. Valida duración positiva y nombres repetidos. La omisión de una fila existente no se presenta como borrado porque el endpoint no elimina registros.

Equipo edita perfiles profesionales, estado, rol descriptivo, capacidad y servicios. Muestra por separado si existe acceso de aplicación y enlaza al gestor canónico de usuarios/roles, donde se conserva la protección del último administrador. No ofrece `owner` ni crea cuentas ficticias. La garantía final del último administrador debe seguir existiendo en backend.

## Horarios, disponibilidad y excepciones

El horario admite los siete días, varios intervalos y días cerrados. Antes de guardar verifica apertura anterior a cierre y ausencia de solapes. Las reglas de reserva mantienen intervalo, antelación, horizonte, margen, cancelación, reprogramación y capacidad con límites del contrato.

La interfaz no inventa huecos: aclara que la disponibilidad se calcula en backend. Las excepciones se cuentan desde su fuente real y se gestionan en Business Admin, evitando duplicar el editor. Cuando la fuente Owner no devuelve reglas avanzadas actuales, exige confirmar expresamente los valores mostrados antes de aplicarlos.

## Página pública y marca

Marca cubre tema, plantilla, paleta y texto alternativo. Logo y galería se consultan o editan en Negocios mediante el editor ya endurecido; no hay subida automática ni un segundo gestor de medios. Contenido público incluye titular, descripción, CTA, horario textual, reseñas y SEO existentes. Hasta activar, el servidor conserva `noindex`.

## Canales

Canales separa disponibilidad comercial, conexión, candidatura, aprobación y salud para Instagram y WhatsApp. Ofrece destinos a Integraciones y Candidaturas, pero no contiene aprobación, conexión manual ni campos de secretos. “Continuar sin conectar” usa la omisión soportada. Readiness sigue siendo quien decide si la ausencia es bloqueante.

## Plan y créditos

El paso muestra plan, créditos incluidos/adicionales y periodo dentro de sus límites. Explica que se trata de una inicialización idempotente, no de facturación, precio, impuestos, renovación ni cobro. Tras completarse queda en consulta porque repetir el endpoint no promete reasignar el plan. Guardarlo nunca activa el negocio.

## Revisión y readiness

La revisión agrupa identidad, contacto, servicios, equipo, horarios, página pública, canales y plan usando exclusivamente estados de sesión. Cada bloque enlaza al paso exacto. Debajo, readiness presenta bloqueos, recomendaciones, comprobaciones correctas/no aplicables y errores, con mensaje, remediación y destino devueltos por backend.

La versión no se imprime: permanece en memoria y se envía como `expected_readiness_version`. Cualquier guardado la invalida. Si la activación devuelve conflicto, se descarta y se exige comprobar de nuevo.

## Preview, activación y resultado

Preview consulta la ruta real y refleja sus garantías de `noindex`/`nofollow`, reservas y automatizaciones deshabilitadas y ausencia de consumo de créditos. No publica ni contiene una acción de activación implícita.

Activar exige motivo, readiness actual listo, confirmación crítica y envío de la versión esperada. La interfaz espera backend y refresca Dashboard, Negocios, Altas, canales y accesos. No aprueba canales ni habilita automatizaciones.

El resultado confirmado ofrece Business Admin y landing mediante rutas locales con slug codificado, canales y Negocios. El administrador y los canales pendientes solo se describen cuando sus fuentes lo confirman. Un negocio ya activo permanece consultable sin parecer editable.

## Abandono, reanudación y conflictos

Al abandonar se pierde únicamente la edición aún no enviada; el diálogo lo explica. Al reanudar se consulta la sesión, su paso actual y sus datos, sin depender del navegador ni crear otra alta.

HTTP 409 se presenta como conflicto de edición. El DOM mantiene temporalmente la copia no sensible, ofrece recargar la versión guardada y nunca fusiona o sobrescribe en silencio. No se muestra detalle crudo.

## Errores parciales y rendimiento

La carga principal es independiente de availability ampliada, excepciones, automatizaciones, créditos y accesos. `Promise.all` tolerante a rechazo permite que cada fallo muestre su aviso sin borrar formularios ni readiness ya visible. Las fuentes no se consultan por render; se cargan una vez por apertura y bajo demanda al reintentar. La creación y cada mutación tienen bloqueo de doble acción.

## Navegación contextual

Dashboard, Negocios y Altas abren el ID seleccionado internamente sin mostrarlo. Readiness enlaza por clave real. Equipo y Marca abren la sección exacta de Negocios; Canales abre Integraciones o Candidaturas. Los enlaces de Business Admin y página pública son destinos locales conocidos, con slug codificado y `rel="noopener"` cuando abren otra pestaña.

## Responsive

- ≥901 px: lista lateral completa y contenido legible.
- ≤900 px: cabecera apilada y selector de pasos compacto, sin rejilla horizontal.
- ≤600 px: formulario a una columna, controles a 16 px para evitar zoom, horarios y acciones apilados.
- Las acciones usan safe area inferior y el diálogo limita su alto con `100dvh`.

La estructura cubre 360, 390, 768, 1024, 1280 y 1440 px; la comprobación visual autenticada se aplaza según la decisión del sprint.

## Accesibilidad

Se conserva el `h1`, shell y skip link Owner. El paso usa `h3` enfocable, lista semántica y `aria-current="step"`; los formularios emplean `label`, `fieldset`, `legend`, ayuda y validación nativa. Los estados guardando/guardado y errores usan regiones acotadas, sin anunciar cada tecla. El diálogo tiene `role="dialog"`, modal, Escape, focus trap y retorno de foco. Se conservan foco visible, botones nativos, texto además de color, reduced motion y objetivos táctiles.

## Seguridad

- Gate y aislamiento por negocio permanecen en backend.
- IDs solo viajan en llamadas y atributos internos; nunca son texto visible.
- Todo contenido variable insertado en HTML se escapa.
- No se solicitan ni representan tokens, secretos, IDs de proveedor, payloads, metadatos, SQL o trazas.
- Los errores se traducen por código HTTP.
- Solo se abren rutas locales conocidas con parámetros codificados.
- No hay datos sensibles en almacenamiento del navegador ni logs nuevos.

## Pruebas

`backend/tests/test_owner_onboarding_complete.py` verifica arquitectura, entradas, creación, los 15 pasos y orden, estados, progreso, guardado, doble acción, abandono, conflicto, editores, separación de acceso, availability/excepciones, marca/medios, canales, créditos, revisión, readiness/versionado, preview, activación/resultado, refresh, errores parciales, escaping, URLs, DOM, responsive, accesibilidad y ausencia de endpoints nuevos.

También se ejecutan las pruebas de shell, Dashboard, Negocios/Aprobaciones, Integraciones/Operaciones, las relacionadas con los contratos backend y la suite completa, además de Ruff y `git diff --check`.

## Limitaciones y validación visual pendiente

No se fabricaron sesión, estados, datos ni capturas. Quedan para QA final autenticado:

- 1440 × 900: creación, shell, servicios, horarios, revisión y activación.
- 1024 × 768: equipo y página pública.
- 768 × 1024: navegación de pasos.
- 390 × 844: creación, formulario, readiness y activación.
- 360 × 800: error, conflicto y cambios sin guardar.
- Teclado completo, zoom 200/400 %, NVDA o VoiceOver y múltiples negocios.

## Deuda

- La fuente principal no expone la identidad legible de quien inició el alta; no se presenta un ID como sustituto.
- La lectura Owner de availability no expone todas las reglas avanzadas del payload de booking; el frontend exige confirmación antes de aplicar valores no verificables.
- Logo, galería, excepciones y membresías conservan sus editores canónicos y no se duplican.
- La protección del último administrador se conserva en interfaz; debe permanecer garantizada en backend ante cualquier cliente.
- La validación visual y E2E autenticada corresponde al QA final, no a 5E.1.
