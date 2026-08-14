# Social Content Intelligence (Sprint 9A)

## Objetivo y límites

Social Content Intelligence traduce señales persistentes del negocio en propuestas editoriales
explicables. Growth determina qué ocurre; RRSS propone qué comunicación pública puede ayudar. Una
`SocialContentProposal` no es copy, creatividad, borrador ni publicación. Sprint 9A no usa LLM, no
decide descuentos, no hace targeting y no llama a Meta.

El flujo es:

```text
BusinessGrowthSignal + BusinessCalendarEvent + BusinessReview + servicios + assets
                                 ↓
                SocialContentIntelligenceService
                                 ↓
                    SocialContentProposal
                                 ↓ (Sprint 9B)
                 InstagramContent ya existente
```

## Pre-existing social work audit

Se inspeccionaron antes de editar los 21 archivos modificados y los 7 archivos nuevos que estaban
fuera de commits. No se resetearon, descartaron ni prepararon. Pertenecen a Sprint 6C.1 y extienden
los commits consolidados de 6A (flujo editorial) y 6B (scheduler/publicación simulada).

### Funcionalidad encontrada

- `admin.js`, `index.html` y `owner.js`: indicadores de publicación real/simulada, estado técnico,
  IDs/permalink y restricciones JPEG en las superficies existentes Owner/Admin.
- configuración y ejemplos de entorno: modo `simulated|meta`, acuse de riesgo, Graph API,
  timeouts y URLs firmadas de assets.
- router, schemas y servicio de Instagram: historial/resultados de jobs y metadatos seguros.
- provider/login/adapter/worker: scope de publicación, selección de adapter, etapas persistentes
  `creating_container` y `publishing`, transacciones cortas, recuperación e incertidumbre segura.
- siete archivos nuevos: entrega HMAC temporal de assets, validación de imagen, cliente Meta,
  tests de publicación real y dos documentos operativos.
- locks y configuración de tooling: Pillow, psycopg y entradas mypy.

### Clasificación

- **Sprint 6 consolidado y completo:** modelos `InstagramContent`, versiones, raw/final assets,
  validación, comentarios, `InstagramPublishJob`, scheduler y publicación simulada. 9A reutiliza
  estos contratos ya consolidados como frontera futura y para contar material, sin modificarlos.
- **6C.1 funcionalmente desarrollado pero no consolidado:** publicación real de una imagen JPEG,
  cliente Meta, entrega firmada y recuperación del worker tienen implementación, tests y runbook.
  Sigue siendo trabajo externo a 9A porque permanece sin commit y la activación real depende de
  configuración/permisos operativos de Meta.
- **Parcial:** validación global pendiente del árbol 6C.1, despliegue externo de Meta y primera
  publicación controlada. Carruseles, vídeo, Reels, Stories y analítica están declaradamente fuera
  de ese incremento.
- **Obsoleto:** no se identificó código claramente obsoleto. La publicación simulada no es
  obsoleta: sigue siendo el modo predeterminado y fallback seguro.
- **Reutilizable:** `InstagramContent` es el destino futuro 9B; `InstagramRawAsset`,
  `InstagramFinalAsset` y galería aportan contexto de material sin duplicar binarios. El adapter,
  worker y endpoint firmado de 6C.1 no son dependencia de propuestas.

9A solo añade hunks propios en `admin.js`, `index.html`, `main.py` y `pyproject.toml`; el commit se
construye por selección exacta para excluir los hunks preexistentes de 6C.1.

## Modelo

`SocialContentProposal` persiste lifecycle, objetivo, tipo, prioridad y score, servicio, evento o
reseña fuente, motivo, evidencia agregada acotada, formatos, CTA, ángulo, disponibilidad/requisito
de assets, ventana temporal, expiración, aceptación y snapshot. `dedupe_key` es único por negocio.

`SocialContentProposalSignal` permite asociar varias señales normales a una propuesta. No hay un
blob de señales ni una segunda copia de ellas.

El repositorio solo tenía `ReviewRequest`: una solicitud saliente que incluye datos del cliente y
no demuestra que exista una reseña. Por eso 9A incorpora `BusinessReview`, fuente mínima separada
para reseñas recibidas: origen/ID externo, rating, texto, fecha, servicio opcional, estado y permiso
explícito de uso social. No existe endpoint de ingesta en 9A. El motor jamás copia su texto a la
propuesta o al response; solo conserva ID interno, rating, fecha y autorización.

## Lifecycle

- `active`: visible y reevaluable.
- `accepted`: el usuario eligió “Usar idea”; es terminal en 9A y conserva snapshot.
- `dismissed`: decisión explícita; una reevaluación del mismo `dedupe_key` no la reactiva.
- `resolved`: desapareció la señal, el servicio quedó inactivo o dejó de ser candidata.
- `expired`: la ventana temporal terminó antes de la evaluación.

Solo propuestas `active` pueden aceptarse o descartarse. Ambas mutaciones son idempotentes si se
repite el mismo resultado. Una propuesta aceptada no vuelve a `active` aunque cambie la señal.

## Reglas deterministas

| Entrada | Tipo / objetivo | Score base | Formatos | Ángulo | CTA |
|---|---|---:|---|---|---|
| baja ocupación futura | `availability_push` / `fill_capacity` | 90 | Story, Reel, Post | disponibilidad | reservar |
| pool agregado de retorno | `return_activation` / `reactivate_customers` | 70 | Story, Carrusel | beneficio general | descubrir servicio |
| baja ocupación + retorno de servicio | `availability_push` / `fill_capacity` | 100 | Story, Reel | ventana limitada | reservar |
| evento a <= 14 días | `seasonal_content` / `seasonal_activation` | 75 | Story, Reel, Post | estacional | disponibilidad |
| evento a > 14 días | igual | 65 | igual | estacional | disponibilidad |
| caída de demanda | `service_push` / `promote_service` | 60 | Reel, Carrusel | proceso | descubrir servicio |
| reseña positiva utilizable | `review_social_proof` / `social_proof` | 40 | Post, Story | testimonio | ninguno |
| sin necesidad >= 35 | `evergreen_content` / `educate` | 10 | Carrusel, Story | FAQ | saber más |

La severidad añade 8 puntos para `high` y 4 para `medium` a reglas de señales no estacionales.
Score >= 70 es prioridad alta, >= 35 normal y el resto baja. No hay ML ni score oculto.

La caída de demanda usa siempre `process`, que es un ángulo conceptual seguro. No infiere
beneficios técnicos/médicos. `before_after` existe en el vocabulario, pero el motor no lo recomienda
sin metadata de material apropiada. No se crea descuento ni porcentaje.

## Composición, cadencia y dedupe

Una señal de ocupación se combina con cada pool agregado vinculado a un servicio activo. Las dos
señales quedan relacionadas con una única propuesta de score 100; el pool global redundante se
suprime cuando existe uno de servicio. El texto habla de un grupo agregado y nunca de personas.

Los límites V1 centralizados son 8 propuestas activas por negocio y 2 por servicio. El fallback
evergreen usa bucket semanal y una ventana de 14 días. Cada regla deriva su identidad del negocio,
tipo, servicio, señal/evento/reseña y bucket ya persistido en la fuente. Una propuesta descartada,
aceptada, resuelta o expirada no se recrea con la misma identidad; una nueva ventana fuente puede
crear una identidad nueva.

La tarea existente de mantenimiento incorpora `--task social-content-intelligence`. Es idempotente,
trabaja sobre señales persistentes y no crea scheduler paralelo. En dry-run toda mutación se revierte.

## Evidencia, assets y privacidad

La evidencia usa allowlists por tipo de señal: porcentajes, conteos agregados, periodos y baseline.
Nunca serializa `CustomerOpportunity`, `Customer`, `CustomerMemoryItem`, conversaciones o texto de
reseña. Un pool due menor de 4 se rechaza defensivamente aunque Growth ya aplique sus propios mínimos.

Los assets se cuentan en galería activa e `InstagramRawAsset` por negocio. La propuesta declara
`available`, `count` y scope `business`; no afirma asociación a un servicio inexistente y no copia
archivos. Sin material recomienda `new_photo`, o `review` en prueba social.

Customer Memory individual no se consulta. No se implementa agregación de memoria en 9A porque no
existe una infraestructura anonimizada con cohortes y gobernanza suficientes.

## Snapshot y frontera 9B

Al aceptar se congela objetivo, tipo, servicio, motivo, evidencia allowlisted, formatos, CTA,
ángulo, assets y ventana, junto con `accepted_at` y `accepted_by_user_id`. No se guardan nombres,
teléfonos, emails, chats ni memoria sensible.

9B podrá convertir ese snapshot en el `InstagramContent` existente. Deberá comprobar antes si hay
un contenido equivalente activo y enlazar explícitamente propuesta y contenido; 9A no crea una
entidad `SocialContentDraft` paralela ni altera el scheduler/publicador de Sprint 6.

## API y Admin

La API tenant-scoped expone listado con filtros `status`, `objective`, `type`, `service` y
`priority`, detalle, summary, accept y dismiss. Usa el permiso existente de acceso al negocio para
admin/staff, aislamiento por slug + business ID y auditoría de mutaciones.

Admin muestra “Ideas recomendadas” dentro de Contenido de Instagram. Cada tarjeta enseña prioridad,
motivo, objetivo, formatos, ángulo, CTA y material, con “Usar idea” y “Descartar”. Las ideas se
cargan aunque el módulo editorial de Instagram aún no esté activado.
