# Sprint 6B: planificación y publicación simulada de Instagram

Este sprint añade una cola persistente y un worker independiente al flujo editorial de 6A. No
existe ninguna llamada a Instagram Graph API: `SimulatedInstagramPublishingAdapter` produce IDs y
permalinks deterministas a partir de la clave de idempotencia de negocio, contenido y versión.

## Modelo y garantías

`instagram_publish_jobs` conserva una fila única por versión. Sus estados son `queued`, `claimed`,
`simulating_publish`, `published`, `retry_wait`, `failed`, `action_required` y `cancelled`. La clave
`instagram-publish:{business_id}:{content_id}:{version_id}` y la unicidad de `content_version_id`
impiden crear o publicar dos veces la misma versión. El histórico no se borra al reprogramar,
cancelar, desactivar el servicio o invalidar una versión.

Un job solo es ejecutable si el servicio de contenido está activo, la versión sigue siendo la
actual y validada, el control Instagram está `approved` con entrega integrada habilitada y la
integración está conectada/degradada sin una salud bloqueante. Estas condiciones se comprueban al
programar y de nuevo justo antes del adaptador.

Los cambios de caption, formato, assets, orden o portada invalidan la validación y cancelan el job
no iniciado. Cambiar únicamente fecha/hora conserva la validación y reprograma la misma fila. Si la
ejecución ya empezó, la operación pasa a `action_required` para evitar un segundo efecto incierto.
Una validación tardía nunca genera trabajo ejecutable hasta que el Owner elija una fecha futura.

Todas las fechas del job se manejan en UTC. Una fecha sin offset se interpreta en la zona del
negocio (`Europe/Madrid` por defecto); las horas inexistentes o ambiguas por DST se rechazan con
422, salvo que la fecha ambigua incluya un offset explícito.

## API

Owner, bajo `/api/owner/businesses/{business_id}/instagram-content`:

- `POST /contents/{id}/schedule`
- `PATCH /contents/{id}/publish-job/reschedule` (alias explícito de `planned-date`)
- `POST /contents/{id}/publish-job/cancel`
- `POST /contents/{id}/publish-now` (encola para el worker; no ejecuta en HTTP)
- `POST /contents/{id}/publish-job/retry`
- `GET /contents/{id}/publish-jobs`

El Business Admin solo puede consultar `GET /contents/{id}/publish-jobs` bajo su prefijo. Los
detalles de contenido también incluyen `publish_jobs`. Staff y Customer no tienen acceso. Todas las
consultas de recursos filtran por negocio.

## Fuera de alcance

No se implementan Meta/Graph API real, containers reales, URLs firmadas, Reels, Stories,
analíticas, TikTok ni trabajo del Sprint 6C.
