# Canales y automatizaciones del Business Admin — Sprint 5B.5

Fecha: 4 de agosto de 2026.

## Resultado

Las antiguas áreas **Canales** y **Mensajes automáticos** se presentan como una sola familia operativa:

```text
Canales y automatizaciones
├── Resumen
├── Instagram
├── WhatsApp
└── Respuestas automáticas
```

Antes, el onboarding mezclaba disponibilidad, aprobación, capacidades y salud en una tarjeta, mientras que reglas y plantillas estaban dentro de Conversaciones y el outbox asistido tenía una pestaña propia. Ahora cada canal separa seis dimensiones: disponibilidad, conexión, aprobación, envío desde AutonoGrow, respuestas automáticas y salud. Conversaciones conserva un acceso directo; los IDs, hashes y contenedores heredados permanecen.

No se modificó backend, modelos, migraciones, endpoints, payloads ni permisos. Tampoco se añadió polling, renovación de tokens o activación local de capacidades.

## Permisos reales

La interfaz es una representación de las decisiones del servidor, no un sustituto de autorización.

| Acción | Business Admin | Owner | Requiere Meta | Requiere aprobación |
| --- | --- | --- | --- | --- |
| Conectar Instagram o WhatsApp | Sí, cuando `can_request` y la política lo permiten | Sí | Sí | La candidatura resultante, sí |
| Solicitar revisión | Implícita en la candidatura oficial | Revisa la candidatura | Sí | Sí |
| Aprobar candidatura | No | Sí | No | Es la propia aprobación |
| Activar envío integrado | No | Sí | No | Sí |
| Activar capacidad de automatización por canal | No | Sí | No | Sí |
| Comprobar salud | Sí, cuando existe integración aprobada | Sí | Sí | Sí, para operar |
| Reconectar | Sí, cuando el estado lo requiere | Sí | Sí | La nueva candidatura, sí |
| Suspender o revocar | No | Sí | No | No |
| Editar reglas y plantillas | Sí, si es Business Admin y la capacidad está autorizada | Sí | No | Depende del canal |
| Modificar plan o créditos | No | Sí | No | No |

No se muestran botones Owner deshabilitados. La ausencia de una acción responde al contrato real (`can_request`, estado comercial, salud y capacidades).

## Arquitectura y contratos

- Escritorio: navegación secundaria vertical y contenido de ancho legible.
- Tablet: navegación de cuatro categorías en cuadrícula y tarjetas apilables.
- Móvil: navegación secuencial y formularios, estados y acciones en una columna.
- Los destinos conservan `channels` y `messages`; se añaden `channel-instagram` y `channel-whatsapp` como vistas del mismo estado cargado.
- Se conservan `channel-onboarding-list`, `channel-onboarding-feedback`, `conversation-automation-panel`, `conversation-automation-content`, `conversation-templates-panel`, `conversation-template-list`, `message-status-filter` y los contenedores de outbox.
- La pestaña primaria antigua `messages` sigue en el DOM como contrato legado, pero queda oculta. La entrada principal activa es **Canales y automatizaciones**.

La navegación y todas las acciones usan listeners delegados registrados una sola vez. Cambiar de categoría conserva el hash y protege cambios pendientes.

## Resumen y estados

Las tarjetas de Instagram y WhatsApp no condensan todo en un badge. Cada una presenta:

1. disponibilidad comercial;
2. conexión;
3. aprobación;
4. envío integrado;
5. respuestas automáticas;
6. salud.

Los estados comerciales se traducen sin mostrar valores desconocidos crudos: `available` es **Disponible**, `pending_approval` es **Pendiente de revisión**, `approved` es **Aprobado**, y `suspended`/`revoked` conservan una descripción humana. `not_allowed` se presenta como **No disponible**.

La salud usa estas traducciones: aún no comprobado, funciona correctamente, puede necesitar atención, funciona con problemas, necesita tu atención, debes volver a conectar, canal suspendido y no se ha podido comprobar. El mensaje acompaña siempre al color. “Sin acciones pendientes” aclara que esto no significa que envío o automatización estén activados.

## Instagram

La vista muestra únicamente la etiqueta amigable de la cuenta cuando existe, conexión, aprobación, capacidades, salud y última comprobación fiable. Las acciones posibles se derivan del estado: conectar, comprobar ahora o volver a conectar.

El inicio y la reconexión reutilizan las URLs entregadas por backend. Antes de redirigir se exige HTTPS, host exacto `www.instagram.com`, path exacto `/oauth/authorize` y ausencia de credenciales embebidas. La interfaz no construye OAuth ni muestra token, scopes, App ID, account ID, state, respuestas Graph o errores técnicos.

## WhatsApp

La vista solo muestra el número redactado cuando el diagnóstico seguro lo incluye. Embedded Signup conserva SDK oficial, configuración pública validada, origin HTTPS de Facebook, state backend, código de autorización y payload existentes.

La entrega distingue:

- **Envío desde AutonoGrow**: capacidad integrada controlada por Owner.
- **Modo asistido**: “Abrir en WhatsApp” prepara el texto y una persona completa el envío fuera de AutonoGrow.

Se explica la ventana real de 24 horas desde el último mensaje del cliente. No se promete un sistema de plantillas de Meta. No se solicita ni muestra PIN, WABA ID, `phone_number_id`, App Secret o token.

## Aprobación y reconexión

Conectar una cuenta crea una candidatura y no activa capacidades. El estado pendiente indica que AutonoGrow debe revisarla. La interfaz no ofrece aprobar, activar envío, activar la capacidad de automatización, suspender, revocar o cambiar disponibilidad comercial.

En Instagram y WhatsApp la reconexión explica la semántica implementada: se vuelve a iniciar el flujo oficial y la integración anterior continúa hasta que la nueva candidatura sea revisada y aprobada. Una respuesta de Meta no sustituye localmente la integración.

## Salud y errores parciales

Onboarding y salud se solicitan en paralelo y se resuelven por separado. Cada carga tiene versión para descartar respuestas obsoletas. Un fallo de salud no borra la información comercial; un fallo de onboarding no borra un diagnóstico anterior. Instagram y WhatsApp renderizan sus propios estados y feedback.

El diagnóstico no presenta contadores de fallos, códigos internos, metadata, trabajos, locks, backoff, scopes ni caducidad del token. La comprobación manual bloquea repeticiones por canal/acción, informa de que está trabajando y reutiliza el refresco operativo normal; no crea un intervalo nuevo.

## Automatizaciones

El frontend continúa editando los ajustes y reglas existentes. Una automatización solo puede activarse en la interfaz cuando coinciden:

- capacidad global habilitada por AutonoGrow;
- periodo activo;
- al menos un canal aprobado con `automation_enabled`;
- canal sin reconexión requerida ni salud bloqueante.

El backend sigue siendo la autoridad final. Una configuración ya activa puede desactivarse aunque aparezca un bloqueo, para no impedir una acción segura. Cada regla muestra nombre amigable, aplicación a canales autorizados, modo, plantilla, estado, extracto y motivo de bloqueo. No se muestran rule ID, job, evento, payload, worker o processor.

## Plantillas y variables

Las plantillas reales son compartidas por las automatizaciones autorizadas; el modelo no les asigna un canal propio. Por eso la interfaz dice “canales con automatización autorizada” y no inventa compatibilidades.

Las únicas variables documentadas y validadas son las que soporta el renderizador actual:

| Variable | Significado |
| --- | --- |
| `{business_name}` | nombre del negocio |
| `{business_slug}` | identificador público del negocio |
| `{public_booking_url}` | enlace público de reserva |
| `{business_phone}` | teléfono del negocio |
| `{business_address}` | dirección del negocio |

No se documentan `{cliente}`, `{fecha}`, `{hora}` o `{servicio}` porque este motor no las soporta. La validación rechaza nombre o contenido vacío, nombre mayor de 160 caracteres, contenido mayor de 10.000, variables desconocidas y llaves sin cerrar. La vista previa sustituye valores conocidos mediante texto y nunca interpreta HTML.

## Créditos

Créditos se muestra como una tarjeta separada de salud. Expone disponibles, incluidos restantes, adicionales, porcentaje y estado del periodo. Explica que afectan a respuestas generadas automáticamente y no inventa precio o equivalencia monetaria. Business Admin no puede comprar, ajustar ni modificar el plan.

## Guardado, concurrencia y polling

Se reutilizan `configurationSnapshots`, `configurationDirtyKeys` y `configurationMutationKeys`. Existen snapshots independientes para ajustes generales, cada regla, cada plantilla y la plantilla nueva. La navegación y `beforeunload` avisan antes de abandonar una categoría con cambios.

Un bloque no puede guardar si otro bloque de esta categoría tiene cambios, evitando que la recarga canónica los sobrescriba. Las mutaciones duplicadas quedan bloqueadas. Los refrescos en segundo plano no renderizan reglas o plantillas si hay cambios pendientes. Después de una mutación se refrescan Conversaciones, Dashboard/operaciones y el estado de canales mediante el pipeline existente.

Los únicos ritmos siguen siendo `conversationThread`, `conversationList` y `operations`. No se añadió `setInterval` ni un health polling agresivo.

## Endpoints reutilizados

- `GET /api/admin/businesses/{slug}/channel-onboarding`
- `POST /api/admin/businesses/{slug}/channel-onboarding/{channel}/request` (fallback existente)
- `GET /api/admin/businesses/{slug}/channels/health`
- `POST /api/admin/businesses/{slug}/channels/{channel}/health-check`
- `POST /api/admin/businesses/{slug}/channels/instagram/reconnect`
- `POST /api/admin/businesses/{slug}/integrations/instagram/oauth/start`
- `POST /api/admin/businesses/{slug}/integrations/whatsapp/embedded-signup/start`
- `POST /api/admin/businesses/{slug}/integrations/whatsapp/embedded-signup/complete`
- CRUD existente de `conversation-templates`
- `GET /conversation-automation` y `PATCH` de settings/rules existentes
- `GET /integrations/status` conservado como contrato seguro de compatibilidad
- endpoints existentes de `message-outbox`

Todas las rutas conservan `getBusinessSlug()` y las credenciales de sesión seguras. No se introdujo ninguna ruta nueva.

## Responsive y accesibilidad

La estructura cubre estáticamente 360, 390, 768, 1024 y 1440 px: no usa tablas, limita cada grid con `minmax(0, 1fr)`, apila formularios y acciones en móvil, conserva objetivos táctiles y añade `safe-area` al bloque inferior. No se fuerza overflow global.

La página mantiene un único `h1`. Cada vista tiene título asociado, navegación secundaria con nombre y `aria-current`, carga con `aria-busy`, estados textuales, labels, ayudas y errores enfocados. Los feedback de acciones usan regiones moderadas `role=status`; salud completa no es `aria-live`. El foco pasa al título al cambiar de categoría, los botones conservan foco visible del sistema compartido y movimiento reducido desactiva transiciones del área.

## Seguridad

- nombres, etiquetas, teléfonos, plantillas y mensajes dinámicos se escapan o asignan con `textContent`;
- OAuth valida protocolo, host, path y credenciales antes de redirigir;
- Embedded Signup valida SDK, configuración y origin antes de completar;
- los errores visibles de acciones Meta son genéricos y no interpolan detalles crudos;
- los botones se derivan de permisos/estado backend y se bloquean contra doble envío;
- una recarga usa siempre el slug actual y las respuestas obsoletas se descartan;
- no se muestran access/refresh token, secretos, states, hashes, fingerprint, IDs internos, scopes o payloads.

## Pruebas y validación

`backend/tests/test_admin_channels_automations.py` cubre arquitectura, contratos, estados separados, salud, acciones oficiales, URL/origin, reconexión, modo asistido, autorización de automatización, créditos, variables, límites, escaping, dirty state, concurrencia, responsive, accesibilidad y reutilización del polling.

También se ejecutan los contratos de shell, polling, Dashboard, Agenda, Conversaciones, Configuración; las suites existentes de control de canales, OAuth/Embedded Signup, Instagram/WhatsApp, salud, mensajería, automatización y créditos; `ruff`, `git diff --check` y la suite completa.

## Limitaciones y validación manual pendiente

No había una sesión autenticada con los escenarios solicitados ni se permite fabricar estados o alterar la base de datos. Por ello no se generan capturas en `docs/ux/screenshots/5B5/`.

Validación manual pendiente con datos reales:

1. abrir Resumen a 1440 × 900 con ambos canales;
2. verificar Instagram conectado y WhatsApp pendiente de aprobación;
3. reproducir una reconexión requerida sin sustituir la integración anterior;
4. revisar Automatizaciones a 1024 × 768 y WhatsApp a 768 × 1024;
5. validar Resumen/onboarding/vacío o error a 390 × 844 y 360 × 800;
6. recorrer con teclado, zoom 200/400 % y NVDA o VoiceOver;
7. comprobar el retorno OAuth y la ventana emergente de Embedded Signup en navegadores admitidos.

La pantalla Owner, Reseñas, compra de créditos, plantillas oficiales de WhatsApp y renovación automática de tokens quedan expresamente fuera de este sprint.
