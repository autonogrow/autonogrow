# Instagram P1: sincronización y reutilización en Stories

## Alcance V1

P1 sincroniza de forma read-only el media accesible de la cuenta profesional conectada, permite
elegir una imagen o un child de carrusel y genera un JPEG Story 9:16. No implementa el flujo
Admin → Owner, un DAM general, transcodificación de Reels ni un editor gráfico general.

La biblioteca se diseñó con dos fuentes conceptuales (`Instagram` y `Material del negocio`), pero
solo Instagram está activa en P1. La futura fuente de material debe converger sobre
`InstagramRawAsset`; no se ha creado una segunda entidad de "source asset".

## Modelo y procedencia

- `InstagramRemoteMedia` guarda identidad remota, metadata mínima, origen y disponibilidad. La URL
  del provider es privada, efímera y nunca se devuelve en las respuestas Owner.
- `InstagramMediaSyncState` conserva cursor, run ID y último resultado para reanudar una página
  fallida de forma idempotente.
- `InstagramRawAsset(source_kind=instagram)` es la copia fuente materializada únicamente cuando el
  Owner decide reutilizar el media. Mantiene la FK al media remoto y queda fuera de la biblioteca
  actual de material bruto hasta el sprint Admin → Owner.
- `InstagramFinalAsset` referencia ese RawAsset y usa un fingerprint del renderer, checksum fuente
  y transformación. Cada crop/fit es un derivado final; el original nunca se sobrescribe.
- La versión editorial persiste el JSON de transformación y la versión del renderer.

## Sync conservadora

Cada job procesa una página. Si existe cursor se encola una continuación usando el mismo run ID;
un retry repite de forma segura la página. El recorrido completo hace upsert por
`(integration_id, provider_media_id)` y reconcilia publicaciones conocidas a través de
`InstagramPublishJob.provider_media_id`.

La ausencia en un listado o una ejecución parcial nunca marca un media como borrado. Solo al
completar el recorrido se sondea individualmente un número limitado de IDs no vistos. Únicamente
un error inequívoco de media no accesible produce `unavailable`; autenticación, permisos, 429,
5xx o red preservan el estado anterior. Una aparición o GET válido restaura el mismo registro.

El scheduler usa el worker de mantenimiento existente con intervalo conservador configurable y
solo programa integraciones que ya completaron al menos una sincronización. La sincronización
inicial se encola al conectar OAuth o mediante refresh manual; así un despliegue no dispara de
golpe descargas sobre todas las integraciones legacy. El worker de publicación mantiene su cola y
lifecycle independientes.

## Descarga y renderer

La materialización hace GET server-side con HTTPS y puerto 443, validación DNS de todas las
direcciones, rechazo de rangos no públicos, redirects manuales limitados, allowlist de CDN Meta en
staging/production, timeout, límite de bytes, MIME, magic bytes y validación Pillow con límite de
píxeles. No se reenvían tokens al CDN ni se registra la URL firmada.

Preview y Pillow comparten estos parámetros normalizados:

`mode (fill|fit), zoom (1..2.5), position_x/y (0..1), background (dark|light)`.

Ambos calculan la escala base con `max` para fill o `min` para fit, aplican zoom y colocan el
resultado mediante las posiciones normalizadas. Pillow produce RGB JPEG 9:16, calidad decreciente
acotada y un máximo configurable.

## Límites contractuales

- La API oficial permite feed, imágenes, carruseles/children y Reels de la cuenta conectada. Las
  Stories expuestas son activas; P1 no promete historial completo de Stories.
- Las URLs de media no son almacenamiento permanente, por eso se refrescan y materializan al usar.
- Meta no ofrece una señal universal de "deleted" distinguible de otros casos de inaccesibilidad;
  el estado honesto de P1 es `unavailable`.
- Reels aparecen como referencia en la biblioteca pero "Reel → Story" queda deshabilitado hasta
  demostrar compatibilidad MP4 sin transcodificación insegura.
- Se conserva el soporte Creator ya existente. La publicación real de Stories en cuentas Creator
  requiere QA contractual controlado con una cuenta de prueba antes de anunciar compatibilidad. P1
  no ejecuta publicaciones Meta reales ni amplía esa promesa.
