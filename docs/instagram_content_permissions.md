# Matriz de permisos de Contenido Instagram

Esta matriz es el contrato vigente desde el hotfix de Sprint 10A. La aprobación editorial del
negocio y la validación técnica son decisiones distintas: solo la segunda permite programar o
publicar.

| Capacidad | Owner | `business_admin` | `business_staff` |
| --- | --- | --- | --- |
| Ver ideas del negocio | Sí, mediante las operaciones Owner | Sí | Sí |
| Proponer/descartar una idea recomendada | Sí | Sí | Sí |
| Ver contenidos y versiones del negocio | Sí, cualquier negocio | Sí, solo su negocio | No |
| Subir y ver material bruto | Sí | Sí, solo su negocio | No en este hotfix |
| Comentar o proponer cambios | Sí dentro del flujo Owner | Sí, solo su negocio | No |
| Aprobar/rechazar editorialmente | Sí dentro del flujo Owner | Sí, solo la versión actual en revisión | No |
| Crear contenido o una versión final | Sí | No | No |
| Generar, regenerar o editar un paquete final | Sí | No | No |
| Subir assets finales | Sí | No | No |
| Validar técnicamente versión y assets | Sí | No | No |
| Cambiar fecha, programar o reprogramar | Sí | No | No |
| Publicar ahora, cancelar o reintentar un job | Sí | No | No |
| Ver estado e historial de publicación no sensible | Sí | Sí, solo su negocio | No |
| Configurar el servicio | Sí | No | No |

## Contratos de autorización

- Owner usa `/api/owner/businesses/{business_id}/instagram-content` para el flujo final. Las rutas
  heredadas de generación bajo el prefijo Admin también exigen `require_owner` hasta que exista un
  endpoint Owner equivalente.
- `business_admin` usa `/api/admin/businesses/{business_slug}/instagram-content` para lectura,
  material bruto, comentarios y `editorial-review`. La aprobación editorial crea un comentario y
  auditoría, conserva `ready_for_review` y nunca crea `InstagramContentValidation` ni un publish
  job. El rechazo exige una nota y cambia a `changes_requested`.
- `business_staff` conserva únicamente las ideas recomendadas mediante las rutas de inteligencia
  social. No se amplía el acceso a material bruto porque hacerlo requeriría abrir también su
  almacenamiento privado y su entrega autenticada.
- Toda búsqueda de contenido, versión, asset, propuesta o job incluye `business_id`. Una membership
  ajena al slug recibe 403; un ID de otro tenant consultado desde un slug autorizado devuelve 404.

`InstagramContentValidation.validator_role` conserva por compatibilidad el valor histórico
`owner_delegate`, impuesto por el constraint existente. Desde este hotfix ese valor representa una
validación técnica Owner y no requiere delegación del negocio. No se añade una migración para
cambiar una etiqueta interna sin impacto funcional.
