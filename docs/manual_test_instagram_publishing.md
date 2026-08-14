# Prueba manual: planificación y publicación de Instagram

Usar exclusivamente una cuenta profesional de prueba. Para la primera publicación real seguir
también `instagram_real_publish_runbook.md`.

## Preparación

1. Migrar hasta el único head `20260814_19` y arrancar API y worker con modo `simulated`.
2. Activar el servicio de contenido, aprobar entrega integrada y conectar una integración Instagram
   saludable para el negocio.
3. Crear un borrador `single_image`, subir un asset final y enviarlo a revisión.
4. Como Business Admin, aprobar la versión. Confirmar que se muestran el ID de versión, los IDs de
   assets aprobados y el usuario aprobador.

## Planificación

1. Programar una fecha futura desde Admin y confirmar que la UI la muestra en la zona del negocio.
2. Reprogramar y verificar que se conserva el mismo job y aparecen ambos eventos en el historial.
3. Cancelar y confirmar `cancelled` y contenido `validated`.
4. Volver a programar y usar “Publicar ahora”; debe quedar `queued` para ejecución inmediata.
5. Probar una hora inexistente por DST y una ambigua sin offset: ambas deben devolver 422.
6. Repetir como Staff: aprobar, programar, publicar y reintentar deben devolver 403.

## Bloqueo de aprobación

1. Con una versión aprobada/programada, editar caption o assets.
2. Confirmar versión nueva, aprobación anterior invalidada, job cancelado y ausencia de publicación.
3. Cambiar solo la fecha en una versión aprobada: la aprobación debe mantenerse.
4. En modo Meta intentar programar `carousel`, `reel` y `story`: debe aparecer
   `publishing_not_supported_yet`; no debe existir un job ejecutable.

## Worker y recuperación

1. Ejecutar dos workers contra PostgreSQL y confirmar un solo claim/publicación.
2. Simular error temporal antes de `media_publish`: comprobar `retry_wait`, backoff y misma clave.
3. Simular reinicio tras guardar container: debe reutilizarlo.
4. Simular reinicio tras guardar media ID: debe completar sin llamar otra vez a `media_publish`.
5. Simular timeout después de iniciar publish: debe quedar `action_required/unknown_result`; la UI
   no ofrece retry y el endpoint de retry devuelve 409.
6. Corromper o reemplazar el JPEG después del preflight: el endpoint firmado debe devolver 404 y
   Meta no debe recibir el archivo.

## Modo Meta controlado

1. Configurar HTTPS/HMAC, scope, token cifrado, cuenta profesional y acuse explícito; mantener el
   worker detenido hasta revisar el job.
2. Publicar un JPEG 1080×1080 de prueba con `--once`.
3. Verificar container, media ID, permalink, estado `published`, contenido `published`, métricas y
   auditorías. Comprobar visualmente la cuenta.
4. Buscar en logs token, `signature=`, caption y respuesta cruda: no debe aparecer ninguno.
5. Ante resultado ambiguo, detener worker, verificar manualmente cuenta/Meta y no reintentar hasta
   reconciliar el resultado.
