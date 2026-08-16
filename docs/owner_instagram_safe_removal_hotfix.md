# Hotfix Sprint 10A: flujo reactivo y borrado seguro en Owner

Las mutaciones de Contenido Instagram actualizan únicamente el recurso afectado a partir de la
respuesta confirmada. Crear, subir material y eliminar consumen un request; las operaciones de
publicación cuya respuesta es un job añaden una única lectura focalizada. Un conflicto `409`
conserva el mensaje seguro del backend y reconcilia solo ese contenido. Ningún coste depende del
número total de contenidos y la actualización completa queda como recuperación manual.

El Owner bloquea por formulario, material bruto o tarjeta de contenido mientras una operación está
en vuelo. El control afectado muestra una etiqueta específica, el ámbito expone `aria-busy` y el
botón de actualización permanece deshabilitado. Los estados validado, programado y publicado usan
confirmaciones explícitas; el contenido publicado se presenta como «Archivar».

## Política de retirada

- Los contenidos sin historial de publicación se eliminan físicamente junto con versiones,
  relaciones y assets finales huérfanos.
- Un contenido programado cancela primero su job. Si la ejecución ya empezó, toda la operación se
  revierte y responde `409` para impedir un resultado incierto.
- Los contenidos publicados, con historial de publicación o con assets referenciados por otro
  contenido se archivan mediante `archived_at`. Se ocultan de las lecturas operativas, conservando
  jobs, eventos, auditoría e identificadores del proveedor.
- Un material bruto solo puede eliminarse si ningún paquete editorial lo referencia. En caso
  contrario responde `409` y conserva registro y archivo.

Los archivos que van a quedar huérfanos se mueven primero a una zona privada temporal. Si falla la
transacción se restauran; después del commit se purgan. Nunca se elimina un archivo cuyo registro se
mantiene por historial o por una referencia compartida.

## Cobertura frontend

El repositorio no dispone de un runner DOM ni de navegador para el Owner. Para este hotfix se
mantiene la cobertura automatizada disponible: pruebas de contrato backend y pruebas estructurales
sobre el JavaScript para single-flight, bloqueos, textos, confirmaciones, `409`, `429`, eliminación
reactiva y ausencia de recargas completas. No se introduce un framework frontend nuevo solo para
esta corrección; la interacción visual final debe verificarse también en staging.
