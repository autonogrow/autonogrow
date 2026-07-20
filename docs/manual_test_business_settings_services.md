# Pruebas manuales: negocio y servicios configurables

## Preparación

1. Ejecutar `python -m app.seed` con `backend` en `PYTHONPATH`.
2. Iniciar backend y servir el repositorio en un origen permitido por CORS.
3. Abrir `autonogrow-admin/index.html?b=demo-taller` y `autonogrow-landing/index.html?b=demo-taller`.

## A. Editar datos del negocio

1. Cambiar titular y descripción en "Datos del negocio".
2. Pulsar "Guardar cambios" y comprobar el mensaje "Guardado correctamente".
3. Recargar el admin y confirmar que los valores persisten.
4. Abrir la landing y comprobar nombre, categoría, titular, descripción, teléfono, ubicación, horario y enlaces.
5. Desactivar temporalmente el negocio y verificar que la landing pública devuelve `404`, mientras el admin sigue accesible para reactivarlo.

## B. Editar reviews_url

1. Cambiar "Google Reviews URL" y guardar.
2. Crear y completar una cita nueva.
3. Consultar las solicitudes de reseña y comprobar que el snapshot usa la URL nueva.
4. Confirmar que el mensaje `booking_completed_review` contiene la misma URL.

## C. Editar servicio

1. Cambiar precio y duración de un servicio activo y guardarlo.
2. Comprobar los cambios en admin y landing.
3. Consultar `available-slots` y verificar que `end - start` coincide con la duración nueva.
4. Confirmar que una cita creada antes del cambio conserva su `duration_minutes` snapshot.

## D. Crear servicio

1. Introducir nombre, precio, duración mayor que cero y descripción.
2. Pulsar "Crear servicio".
3. Comprobar que aparece activo en admin, landing y selector de reserva.
4. Crear una cita con el servicio nuevo y verificar su duración snapshot.

## E. Desactivar servicio

1. Desmarcar "Activo" en un servicio y guardarlo.
2. Comprobar que aparece atenuado en admin y desaparece de landing.
3. Intentar crear una cita nueva con su `service_id` y esperar `404`.
4. Confirmar que las citas antiguas siguen mostrando nombre y duración snapshot.

## F. Seed

1. Modificar perfil, precio/duración de un servicio y horarios desde admin.
2. Ejecutar `python -m app.seed`.
3. Confirmar que los cambios persisten.
4. Verificar que la seed solo completa campos vacíos y crea servicios u horarios cuando todavía no existen.
5. Confirmar que la limpieza de reservas, clientes, reseñas y mensajes de prueba sigue funcionando.

## Validaciones

- El nombre del negocio y del servicio no pueden estar vacíos.
- La duración debe ser un entero mayor que cero.
- El teléfono vacío es válido; si se informa, debe poder normalizarse para WhatsApp.
- Los nombres de servicio no pueden repetirse dentro del mismo negocio.
- La desactivación es lógica mediante `active=false`; no se borran físicamente servicios desde admin.
