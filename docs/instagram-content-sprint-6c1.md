# Sprint 6C.1: publicación real de imágenes individuales en Instagram

Este incremento conecta el flujo editorial y la cola de 6B con Instagram API mediante
`MetaInstagramPublishingAdapter`. Solo admite una versión `single_image` con exactamente un asset
final JPEG. El modo predeterminado continúa siendo `simulated`; carruseles, vídeo, Reels, Stories,
analíticas y transformaciones siguen fuera de alcance.

## Flujo y persistencia

La factoría `get_instagram_publishing_adapter()` selecciona `simulated` o `meta`. El router nunca
llama a Meta: “Publicar ahora” encola el mismo job persistente y el worker ejecuta estas etapas:

1. Revalida servicio, negocio, canal aprobado, entrega habilitada, integración, salud, versión
   actual, validación, formato, asset y caption.
2. Descifra el access token solo en memoria y genera una URL HTTPS HMAC breve ligada a negocio,
   versión y asset final.
3. Crea `/{ig-user-id}/media` y confirma `provider_container_id` en una transacción corta.
4. Registra el inicio irreversible y llama a `/{ig-user-id}/media_publish`.
5. Confirma `provider_media_id` antes de consultar, de forma best effort, `permalink`.
6. Marca job y contenido como `published` y registra auditoría.

No hay una transacción de base de datos abierta durante una llamada externa. Un reinicio tras
confirmar el container pero antes de iniciar `media_publish` reutiliza ese container. Si el proceso
muere después de registrar el inicio de `media_publish`, o la llamada termina por timeout/conexión,
el job pasa a `action_required`: no se reintenta automáticamente porque el resultado puede ser
desconocido. Si el `media_id` ya quedó confirmado, el reinicio solo completa permalink/estado.

Los estados técnicos nuevos son `creating_container` y `publishing`; `simulating_publish` se
conserva para compatibilidad con 6B. Los IDs de proveedor, permalink, estado y errores seguros se
guardan en `instagram_publish_jobs`. La UI Owner muestra modo, identificador de container abreviado,
media ID, permalink y diagnóstico. Admin recibe estado, resultado, permalink y error en solo
lectura; no recibe container ni metadata técnica.

## Validación previa

Antes de contactar a Meta se exige:

- versión actual, programada y todavía validada;
- formato `single_image` y exactamente un `InstagramFinalAsset` (nunca material bruto);
- JPEG real, MIME `image/jpeg`, extensión `.jpg`/`.jpeg`, archivo no vacío y tamaño coherente;
- máximo 8 MiB, ancho entre 320 y 1440 px y relación ancho/alto entre 0,8 y 1,91;
- decodificación segura con Pillow y SHA-256 comparado con el guardado al subir el archivo;
- caption UTF-8 de hasta 2200 caracteres, enviado exactamente como se guardó.

El endpoint público `GET|HEAD /api/public/instagram-assets/{business_id}/{version_id}/{asset_id}`
solo sirve el asset final actual, programado y validado si `expires` y `signature` son válidos. La
firma usa HMAC-SHA256 y comparación constante; la URL caduca en 30–900 segundos. La ruta física no
se acepta desde el cliente y se comprueba que permanezca dentro de `UPLOADS_DIR`.

La migración no intenta leer archivos durante el DDL: assets finales anteriores quedan con checksum
nulo y el modo real exige volver a subirlos. El endpoint firmado vuelve a comprobar tamaño y
checksum en cada descarga, de modo que una modificación entre preflight y fetch queda bloqueada.

## Permisos de Instagram Login

La publicación requiere `instagram_business_content_publish`, además de los permisos existentes.
No se añade en modo simulado. Al habilitar explícitamente `INSTAGRAM_PUBLISHING_MODE=meta` junto al
acuse de riesgo, las conexiones/reconexiones nuevas lo solicitan y el callback verifica que Meta lo
haya concedido. Las integraciones antiguas no se amplían: quedan en `action_required` hasta una
reconexión controlada.

La app Meta debe tener configurado Instagram API with Instagram Login, el producto/caso de uso de
publicación y el acceso adecuado para ese permiso. En Live mode puede requerir App Review/Advanced
Access; debe verificarse en el panel de Meta antes de activar producción. Referencia primaria:
[colección oficial de Meta para Instagram API](https://www.postman.com/meta/instagram/folder/6raa77c/instagram-api-with-instagram-login).

## Configuración

```text
INSTAGRAM_PUBLISHING_MODE=simulated|meta
INSTAGRAM_REAL_PUBLISHING_ACKNOWLEDGED=false
INSTAGRAM_GRAPH_API_BASE_URL=https://graph.instagram.com
INSTAGRAM_GRAPH_API_VERSION=v23.0
INSTAGRAM_HTTP_CONNECT_TIMEOUT_SECONDS=5
INSTAGRAM_HTTP_READ_TIMEOUT_SECONDS=20
INSTAGRAM_ASSET_URL_BASE=https://api.example.com
INSTAGRAM_ASSET_URL_SECRET=<aleatorio, mínimo 32 caracteres>
INSTAGRAM_ASSET_URL_TTL_SECONDS=300
```

`meta` no arranca sin el acuse explícito, base pública HTTPS y secreto de firma. El token se envía
en `Authorization: Bearer`; no aparece en URL, logs, auditoría ni metadata. Tampoco se registran
caption, URL firmada completa o respuesta cruda de Meta.

## Errores

- temporales antes de la publicación: `retry_wait` con backoff;
- validación/formato: `failed`, editable mediante nueva versión;
- autenticación, permiso, integración o configuración: `action_required`;
- resultado ambiguo tras iniciar `media_publish`: `action_required`, sin retry automático;
- rechazo permanente del proveedor: `failed`;
- fallo al obtener permalink después de publicar: la publicación sigue `published` sin permalink.

La migración `20260806_13` añade el checksum nullable para compatibilidad y amplía el constraint de
estados. Su downgrade convierte cualquier etapa real en curso a `action_required` antes de
restaurar el constraint anterior y elimina la columna nueva.

## Reconciliación 6C.1 en Sprint 9C

| Área heredada | Decisión 9C |
| --- | --- |
| adapter simulado/Meta y cliente HTTP | Conservados; inspección ambigua ahora conserva el estado observable sin asumir éxito |
| URL firmada y endpoint GET/HEAD | Conservados; siguen ligados a tenant, versión aprobada y asset |
| validación JPEG/caption/checksum | Conservada e integrada en un preflight compartido |
| estados, claims, leases y backoff | Conservados; siguen siendo persistentes e idempotentes |
| OAuth y scope de publicación | Conservados; el scope solo se solicita en modo Meta |
| UI Admin de solo lectura | Sustituida por aprobación, planificación, publicación, cancelación y retry autorizado |
| formatos editoriales 9B | Conservados; Meta V1 los rechaza explícitamente salvo `single_image` |
| requirements lock (`psycopg[binary]`, `uvicorn[standard]`) | Conservado: refleja los extras ya declarados en `requirements.in`; Pillow queda como dependencia directa de validación |
| migración/head | No se añade modelo redundante: versión, job y auditoría cubren el cierre; head único `20260814_19` |
