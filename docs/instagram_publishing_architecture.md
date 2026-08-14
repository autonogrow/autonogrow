# Arquitectura de planificación y publicación de Instagram

## Alcance V1

El flujo completo es propuesta → borrador → versión inmutable → aprobación humana → planificación
→ job persistente → adaptador → Meta → historial. La publicación real admite únicamente
`single_image` con un JPEG final. `carousel`, `reel` y `story` permanecen en el modelo editorial,
pero el preflight real los rechaza con `publishing_not_supported_yet`; nunca se convierten ni se
simulan como una imagen.

## Fuente de verdad y bloqueo de versión

- `InstagramContentVersion` contiene caption, formato y enlaces ordenados a assets finales.
- `InstagramContentValidation` identifica aprobador, rol, instante y versión. Los assets aprobados
  son exactamente los enlaces inmutables de esa versión y se exponen como `approved_asset_ids`.
- editar caption, formato o assets crea una versión nueva, invalida la aprobación activa y cancela
  el job recuperable. Cambiar únicamente la fecha no invalida la aprobación.
- `InstagramPublishJob.content_version_id` y su clave estable
  `instagram-publish:{business}:{content}:{version}` impiden dos jobs para la misma versión.
- las reprogramaciones y reintentos reutilizan la misma fila; la secuencia append-only se conserva
  en `AuditLog` y se devuelve como `publication_events`.

## Preflight compartido

`publication_preflight()` se ejecuta al programar, al publicar ahora, al reintentar y de nuevo en el
worker. Comprueba servicio, versión actual, aprobación activa, negocio, control del canal,
integración y salud, pertenencia de assets y cardinalidad de formato. En modo Meta comprueba además
credenciales cifradas, cuenta profesional, scope `instagram_business_content_publish`, caption,
JPEG, checksum, tamaño, dimensiones y aspect ratio. Un fallo no produce un job ejecutable.

Las fechas sin offset se interpretan en `Business.timezone`. Fechas locales inexistentes por DST
se rechazan; fechas ambiguas requieren offset explícito. En base de datos se persiste UTC.

## Ejecución e idempotencia

FastAPI solo modifica estado local. El worker reclama lotes con bloqueo de fila (`SKIP LOCKED` en
PostgreSQL), lease y límite de intentos. Las llamadas HTTP ocurren fuera de una transacción abierta:

1. claim confirmado;
2. creación del container y persistencia inmediata de `provider_container_id`;
3. persistencia de `media_publish_started` antes de la operación irreversible;
4. persistencia inmediata de `provider_media_id`;
5. finalización `published` y permalink best effort.

Un container confirmado puede reutilizarse tras reinicio. Un media ID confirmado permite completar
sin publicar otra vez. Un timeout o pérdida de claim después de iniciar `media_publish` queda en
`action_required/unknown_result` y está excluido del retry. La inspección best effort conserva el
`status_code` observable del container en el código seguro, pero no lo interpreta como prueba de
publicación. La reconciliación manual es obligatoria cuando Meta no devuelve un media ID.

## Entrega segura del asset

Meta recibe una URL HTTPS breve firmada con HMAC-SHA256 sobre negocio, versión, asset y expiración.
`GET` y `HEAD` vuelven a comprobar firma constante, TTL, tenant, versión actual/aprobada/programada,
checksum y confinamiento dentro de `UPLOADS_DIR`. La API nunca acepta una ruta física del cliente.
Tokens, firma completa, caption y respuestas crudas no aparecen en logs ni auditoría.

## Permisos, UI y métricas

Business Admin puede aprobar, programar/reprogramar, publicar ahora, cancelar y reintentar resultados
seguros. Staff recibe 403 y el Owner técnico opera por sus rutas separadas. La UI Admin muestra
plan próximo, zona horaria, versión/assets aprobados, intentos, errores seguros, permalink e historial.

`/publication-metrics` expone por negocio borradores, aprobados, programados, publicados, fallidos,
acción requerida y ratio de éxito. `/internal/metrics` agrega estados globales y contadores de
intentos, éxitos y fallos sin labels de alta cardinalidad.

## Evolución futura

Los formatos futuros ya existen en el dominio editorial. Para habilitarlos se debe añadir una
capacidad explícita al adaptador, validación específica de assets, etapas proveedor e integración
end-to-end. No se debe relajar el preflight V1 ni reutilizar la operación de imagen individual.
