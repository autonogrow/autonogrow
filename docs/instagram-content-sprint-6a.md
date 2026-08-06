# Instagram Content — Sprint 6A

Este sprint incorpora la base editorial colaborativa para preparar contenido de Instagram. No conecta con Meta, no publica y no crea jobs.

## Alcance implementado

- Configuración por negocio del servicio adicional, activable únicamente por Owner.
- Delegación explícita por Business Admin mediante `owner_can_validate_instagram_content`.
- Biblioteca privada de material bruto para Owner y Business Admin.
- Contenido final creado y modificado únicamente por Owner.
- Versiones inmutables con caption, formato, assets ordenados y portada.
- Fecha prevista almacenada en el contenido, fuera de la versión material.
- Comentarios, propuestas y solicitudes de cambios del Business Admin vinculados a versión.
- Validación persistente vinculada a una versión concreta, con historial de invalidación.
- Estados `draft`, `ready_for_review`, `changes_requested`, `validated`, `scheduled` y `cancelled`.
- Auditoría de activación, uploads, versiones, fechas, transiciones, comentarios, delegación y validación.
- Paneles mínimos Owner y Admin.

Los formatos admitidos son `single_image` y `carousel`. Reels y Stories quedan expresamente fuera de este sprint.

## Separación de datos

| Concepto | Persistencia |
| --- | --- |
| Configuración | `instagram_content_settings` |
| Material bruto | `instagram_raw_assets` |
| Contenido final | `instagram_contents` |
| Assets finales | `instagram_final_assets` |
| Versión material | `instagram_content_versions` + `instagram_content_version_assets` |
| Validación | `instagram_content_validations` |
| Comentarios | `instagram_content_comments` |
| Auditoría | `audit_logs` existente |

El material bruto y los assets finales se guardan bajo `_instagram_content`, fuera del árbol `/uploads/businesses` servido de forma estática. Solo se descargan a través de endpoints autenticados con filtro por negocio. Los IDs de material bruto no son aceptados por el contrato de versiones finales, por lo que el material bruto no puede publicarse directamente.

## Flujo y versionado

1. Owner crea el contenido; nace en `draft` con versión 1.
2. Owner sube assets finales y guarda caption, formato, orden y portada. Un cambio real crea la siguiente versión.
3. Owner envía a revisión (`ready_for_review`). Se exige una composición válida: una imagen para `single_image` o al menos dos para `carousel`.
4. Business Admin comenta, propone o solicita cambios. Una solicitud sobre la versión vigente cambia el estado a `changes_requested` e invalida una validación activa.
5. Business Admin valida indicando explícitamente `version_id`. Owner puede hacer lo mismo solo si el Admin mantiene activa la delegación.
6. Owner puede marcar contenido validado y con fecha prevista como `scheduled`. Este estado no crea jobs ni ejecuta publicación.

Cambiar caption, formato, assets, orden o portada crea una versión e invalida la validación activa. Reenviar exactamente el mismo material no crea una versión. Cambiar título o fecha prevista no cambia la versión ni invalida la validación.

## API Owner

Prefijo: `/api/owner/businesses/{business_id}/instagram-content`

- `GET|PATCH /settings`
- `GET|POST /raw-assets`, `GET /raw-assets/{asset_id}/file`
- `GET|POST /contents`, `GET /contents/{content_id}`
- `POST /contents/{content_id}/final-assets`
- `GET /contents/{content_id}/final-assets/{asset_id}/file`
- `PUT /contents/{content_id}/material`
- `PATCH /contents/{content_id}/planned-date`, `PATCH /contents/{content_id}/title`
- `POST /contents/{content_id}/submit-for-review`
- `POST /contents/{content_id}/validate` (solo con delegación activa)
- `POST /contents/{content_id}/schedule`, `POST /contents/{content_id}/cancel`

## API Business Admin

Prefijo: `/api/admin/businesses/{business_slug}/instagram-content`

- `GET /settings`
- `PATCH /settings/validation-delegation`
- `GET|POST /raw-assets`, `GET /raw-assets/{asset_id}/file`
- `GET /contents`, `GET /contents/{content_id}`
- `GET /contents/{content_id}/final-assets/{asset_id}/file`
- `POST /contents/{content_id}/comments`
- `POST /contents/{content_id}/validate`

Los endpoints Admin rechazan Owner, Business Staff, Customer y administradores pertenecientes a otro negocio. Los endpoints Owner exigen el rol global Owner. Todas las consultas de recursos editoriales combinan el identificador del recurso con `business_id`.

## Fuera de alcance

Instagram Graph API, publicación real, workers, scheduler, URLs temporales para Meta, Reels, Stories, analíticas, generación de contenido, TikTok y ejecución automática. `scheduled` es únicamente estado de dominio en este sprint.
