# Social Content Intelligence — arquitectura P1.2

## Mapeo real de actores

Los nombres técnicos históricos no coinciden con los actores de producto:

- `business_admin`, con membresía tenant activa, representa al **Business Owner**. Ve y decide
  únicamente sobre su negocio, expresa interés, decide una promoción y concede la aprobación final
  de una versión.
- `is_owner=true` representa al **AutonoGrow Admin** global. Puede acceder a los negocios desde la
  superficie global, revisar ideas, preparar contenido y registrar la revisión editorial, pero no
  puede expresar interés ni conceder la aprobación final en nombre del negocio.
- `business_staff` no puede realizar decisiones reservadas.

Las carpetas y prefijos legacy `admin`/`owner` se conservan por compatibilidad. Los permisos nuevos
se basan en membresía y privilegio global explícitos, no en el nombre de la superficie.

## Flujo Owner-first

```text
señales agregadas + servicios + calendario + reseñas recibidas utilizables
                                ↓
             SocialContentIntelligenceService
                 (sin consultar materiales)
                                ↓
                  SocialContentProposal active
                                ↓
        Business Owner: Me interesa / Promoción / Ahora no
                                ↓
             SocialIdeaReview única e idempotente
                                ↓
        AutonoGrow Admin: aprobar / ajustar / rechazar
                                ↓
          deterministic_v1 consulta material y crea borrador
                                ↓
       revisión editorial AutonoGrow ligada a version_id
                                ↓
       aprobación final Business Owner ligada a version_id
                                ↓
                     programar / publicar
```

Una `SocialContentProposal(status=accepted)` histórica sin `SocialIdeaReview` no se reinterpreta
como interés del Business Owner, no se migra mediante backfill y no aparece en la cola Owner-first.
Tampoco puede iniciar una generación nueva.

## Ideación, presentación y materiales

El Opportunity Engine usa únicamente señales persistidas, servicio, eventos configurados y
`BusinessReview` realmente recibida y autorizada. `ReviewRequest` no se considera una reseña. La
ausencia de ingesta productiva completa de reseñas sigue siendo deuda explícita.

El motor no consulta galería ni `InstagramRawAsset`. Las columnas legacy
`available_asset_count`/`asset_requirement` se mantienen neutrales por compatibilidad de esquema y
no participan en creación, score, prioridad, servicio elegido o presentación. Con las mismas
señales, cero y cien materiales producen la misma idea y el mismo `opportunity_score`.

`SocialContentPresentationService` convierte determinísticamente reason codes, señales, servicio,
objetivo, formatos y fechas en título, explicación, acción sugerida, razones humanas y
`template_version=owner_idea_es_v1`. Nunca presenta la disponibilidad de material como motivo.

Solo después de “Me interesa”, `SocialProductionReadinessService` informa `ready`, `partial` o
`needs_material` y conteos de imágenes, vídeo, galería, raw e Instagram materializado. Este dato no
modifica el score.

## Señales y deduplicación

Se mantienen las reglas de ocupación, retorno, caída de demanda, ventanas estacionales,
`BusinessCalendarEvent` y reseñas autorizadas. `new_service` usa `BusinessService.created_at`, una
ventana de 21 días, expiración y dedupe por servicio. No intenta inferir “servicio modificado”.

Las ventanas estacionales reutilizan el calendario existente, incluida recurrencia, horizonte,
relevancia, expiración y dedupe. Una propuesta descartada no se recrea con la misma identidad.

## Producción determinista

`deterministic_v1` solo se ejecuta cuando existe `SocialIdeaReview` aprobada por el AutonoGrow
Admin. En esta fase sí puede consultar `InstagramRawAsset`, galería y material materializado desde
Instagram. Recomienda inputs compatibles, pero nunca reescribe retroactivamente el score.

La biblioteca reutiliza `InstagramRawAsset` con `source_kind=business_upload|instagram`; no existe
otra abstracción raw. El campo de origen serializado distingue subida AutonoGrow, subida del negocio
y materialización de Instagram. El original permanece intacto y las transformaciones Story crean
un JPEG final persistente y versionado.

## Promociones

Una señal nunca crea un descuento. Solo la combinación explícitamente elegible de caída de demanda
de servicio y baja ocupación permite al Business Owner solicitar “Estudiar promoción”.

`SocialPromotion` conserva el lifecycle y `SocialPromotionRevision` conserva revisiones inmutables
con tipo/importe, precio habitual snapshot, precio promocional, moneda, ventana, días y alcance. El
precio habitual debe coincidir exactamente con el servicio en el momento de proponer y
`BusinessService.price_amount` nunca se modifica. Solo una revisión `owner_approved` entra en
`deterministic_v1`. Sin costes o márgenes no se hacen afirmaciones de rentabilidad.

Programar no invalida la aprobación editorial. Si el contenido contiene una promoción aprobada,
la fecha debe estar dentro de `valid_from`/`valid_until` y, si se configuraron, de sus weekdays.

## Revisión por versión

`InstagramContentEditorialReview` persiste `pending`, `approved`, `changes_requested` o `rejected`
para un `content_id` y `version_id` únicos. Después de la aprobación AutonoGrow, el
`business_admin` puede crear `InstagramContentValidation` como aprobación final del negocio para esa
misma versión.

Cambiar media, caption, formato, CTA, paquete creativo o promoción crea/cambia una versión e
invalida aprobaciones anteriores. Cambiar solo `planned_publish_at` no crea versión ni invalida la
aprobación.

## Seguridad y auditoría

Todas las lecturas y mutaciones tenant filtran por negocio. El Business Owner A nunca puede usar el
slug de B; el operador global tampoco puede llamar las rutas reservadas al tenant. La auditoría
registra, con el actor técnico real: idea vista, aceptada o descartada; revisión, ajuste o rechazo
AutonoGrow; generación; revisión editorial; aprobación final; solicitud/propuesta/decisión de
promoción; raw upload y raw reuse.

La implementación no incluye LLM, targeting individual ni llamadas de publicación reales a Meta.
