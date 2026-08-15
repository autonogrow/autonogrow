# Social Content Generation V1

## Alcance

Sprint 9B convierte una `SocialContentProposal` aceptada en un borrador del flujo editorial existente. No crea un modelo editorial paralelo, no genera imágenes o vídeo y no publica ni programa contenido automáticamente. El resultado sigue siendo `InstagramContent.status = draft` y debe recorrer revisión, validación y scheduling de 6A/6B.

La relación es explícita y uno a uno: `instagram_contents.source_proposal_id` referencia la propuesta. Borrar o cancelar contenido no borra la propuesta; la clave foránea usa `SET NULL`. Una restricción única evita dos borradores para la misma idea y la generación repetida devuelve el existente.

## Paquete y versiones

Cada `InstagramContentVersion` puede contener un `editorial_package_json` pequeño (máximo 20.000 caracteres), su `generation_source` y `generator_version`. El esquema V1 conserva:

- formato editorial, hook, titular, caption, CTA y ángulo;
- texto en pantalla, dirección visual y shot list;
- slides de carrusel o frames de story;
- entre 3 y 8 hashtags;
- assets recomendados y necesidades pendientes;
- contexto trazable: propuesta, servicio, señales, evento, reseña, fecha de aceptación, avisos y generador.

`static_post` se publica con la composición técnica `single_image`; `carousel`, `story` y `reel` conservan su tipo. El adaptador real 6C.1 sigue bloqueando de forma segura cualquier composición no soportada; Sprint 9B no modifica su worker ni sus contratos de Meta.

Generar crea v1. Regenerar el paquete completo o editarlo manualmente crea v2, v3, etc., copia los enlaces a assets finales de la versión anterior, invalida una validación activa, cancela un job pendiente mediante el servicio existente y devuelve el contenido a `draft`. Nunca se sobreescribe una versión histórica.

## Generador determinista y seguridad

`ContentGenerator` es la interfaz intercambiable. V1 usa `DeterministicContentGenerator` y marca cada salida como `deterministic_v1`; no necesita proveedor LLM.

Las plantillas describen el negocio y servicio con tono cercano y neutral porque el modelo actual no tiene un campo de voz de marca. No inventan precios, descuentos, escasez, resultados o afirmaciones sobre clientes. La reseña fuente solo habilita el ángulo: no se copia texto, nombre ni otro dato personal. Los CTA proceden de un mapa cerrado. Los hashtags se construyen únicamente con nombre, categoría, servicio y ciudad realmente almacenados, más términos genéricos seguros.

La selección de hooks rota de forma determinista contra los últimos doce paquetes del negocio. La estructura específica es:

- reel: texto en pantalla y shot list;
- story: secuencia de frames con texto, visual, CTA y sticker;
- carousel: slides con título, cuerpo y visual;
- static post: titular/texto de imagen y dirección visual.

## Snapshot, frescura y assets

La copy se genera desde `accepted_context_json`, el snapshot inmutable capturado al aceptar. Se bloquea generación/regeneración si la propuesta no está aceptada, expiró, su servicio dejó de estar activo o la reseña dejó de estar usable y autorizada. Si una señal enlazada cambió de estado, el snapshot no se refresca silenciosamente: el paquete expone un aviso para revisión humana.

Los assets siempre se consultan con `business_id`. Se excluyen raw assets y galería inactivos. `service_id` permite asociación estructurada sin deducirla de etiquetas. El ranking prioriza asociación al servicio y después recencia/compatibilidad; solo se recomienda material compatible. Si falta, se declara `new_video`, `new_photo` o `new_photos_for_carousel`. `media_generation_requested` siempre es falso.

## API, permisos y auditoría

Las rutas heredadas bajo el prefijo Admin están protegidas por `require_owner`; Business Admin y
Staff reciben 403 porque generar, regenerar o editar crea una versión final:

- `POST /api/admin/businesses/{slug}/social-content-proposals/{id}/generate`
- `POST /api/admin/businesses/{slug}/instagram-content/contents/{id}/regenerate`
- `PUT /api/admin/businesses/{slug}/instagram-content/contents/{id}/generated-draft`

Las búsquedas incluyen `business_id`; un ID ajeno devuelve 404. Cada mutación material queda auditada sin incluir caption, reseñas, señales completas ni PII. Admin puede proponer la idea y consultar el borrador preparado, pero no generarlo ni editarlo. La matriz definitiva está en `instagram_content_permissions.md`.

## Evolución

Un generador probabilístico futuro debe implementar `ContentGenerator`, conservar el contrato del paquete, declarar versión, aplicar las mismas reglas de seguridad y entrar siempre como borrador versionado. No debe acceder a reseñas crudas ni reemplazar el snapshot aceptado. Cualquier ampliación de formatos publicables se coordina con el adapter y worker correspondiente, no con este generador.
