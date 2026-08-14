# Runbook: primera publicación real controlada de Instagram

No ejecutar este procedimiento con una cuenta o audiencia de producción como primera prueba.

## Preparación

1. Crear un negocio y una cuenta profesional de Instagram exclusivos de prueba, sin campañas ni
   automatizaciones externas.
2. Confirmar en Meta que la app tiene Instagram API with Instagram Login y acceso aprobado a
   `instagram_business_content_publish`. En modo desarrollo, añadir explícitamente las cuentas de
   prueba/roles necesarios.
3. Aplicar Alembic hasta el único head `20260814_19`, desplegar backend y mantener el worker detenido.
4. Configurar un dominio HTTPS público para el backend. Verificar que el proxy enruta
   `/api/public/instagram-assets/` sin registrar query strings.
5. Generar un secreto HMAC independiente y configurar todas las variables de 6C.1, todavía con
   `INSTAGRAM_PUBLISHING_MODE=simulated`.
6. Ejecutar suite, checks de seguridad y una publicación simulada completa.

## Activación explícita

1. Cambiar de forma auditada:

   ```text
   INSTAGRAM_PUBLISHING_MODE=meta
   INSTAGRAM_REAL_PUBLISHING_ACKNOWLEDGED=true
   INSTAGRAM_PUBLISHING_WORKER_ENABLED=false
   ```

2. Reiniciar solo la API. Reconectar la cuenta de prueba para conceder el permiso de publicación;
   verificar en la integración que el scope está almacenado y la salud es utilizable.
3. Preparar un JPEG inocuo de 1080×1080, una caption inequívoca de prueba, aprobar explícitamente
   la versión/assets como Business Admin y programarla. Confirmar que hay un único job y que su
   negocio/versión son los esperados.
4. Habilitar un único worker y ejecutarlo una vez:

   ```text
   python -m app.workers.instagram_publish_worker --once
   ```

5. Detener de nuevo el worker. Comprobar `published`, `provider_media_id`, permalink (si Meta lo
   devolvió), auditorías de las cuatro etapas y la publicación visible en la cuenta de prueba.
6. Revisar logs buscando accidentalmente token, `signature=`, caption o respuestas crudas; ninguno
   debe estar presente.

## Fallos y recuperación

- `instagram_publish_scope_missing` o autenticación: mantener worker detenido, reconectar y volver
  a verificar. No editar scopes ni tokens directamente en base de datos.
- validación de JPEG/caption: crear una versión final nueva y validarla; el backend no transforma.
- error temporal antes de publicar: dejar que el mismo job use el backoff configurado.
- `unknown_result`, `instagram_publish_timeout_unknown*` o claim vencido tras iniciar publish:
  detener el worker, comprobar manualmente la cuenta y Meta, y no usar “reintentar”. Resolver el
  estado mediante procedimiento operativo antes de cualquier publicación nueva. Un sufijo como
  `_finished` solo describe el container observado y no confirma que el post exista.
- container confirmado sin inicio de publish: el worker puede recuperar el mismo job/container.
- media ID confirmado: el worker puede completar el resultado sin volver a publicar.

## Vuelta segura

Para impedir nuevos envíos, deshabilitar primero el worker y después volver a
`INSTAGRAM_PUBLISHING_MODE=simulated`. No borrar jobs, IDs de proveedor ni auditoría. El downgrade
de Alembic no elimina publicaciones de Instagram y nunca sustituye una revisión manual.
