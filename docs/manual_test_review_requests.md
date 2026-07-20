# Pruebas manuales: solicitudes de reseña

## Preparación

1. Ejecutar `python -m app.seed` desde el entorno con `backend` en `PYTHONPATH`.
2. Iniciar el backend y abrir `autonogrow-admin/index.html?b=demo-barberia`.

## A. Completar una cita con reviews_url

1. Crear una cita futura en `demo-barberia`.
2. Abrir el admin y marcarla como completada.
3. Comprobar que aparece el bloque "Solicitud de reseña" con estado "Pendiente".
4. Confirmar en `GET /api/admin/businesses/demo-barberia/review-requests` que existe una solicitud para la cita.
5. Pulsar "Copiar mensaje" y comprobar el feedback "Mensaje copiado" y el estado "Copiada".
6. Pulsar "Marcar como enviada" y comprobar el estado "Enviada" y `sent_at` en la API.

## B. Evitar duplicados

1. Repetir el `PATCH` de la cita a estado `completed` varias veces.
2. Consultar `GET /api/admin/businesses/demo-barberia/review-requests`.
3. Comprobar que solo hay una solicitud con ese `booking_id`.

## C. Negocio sin reviews_url

1. Dejar temporalmente vacío `reviews_url` en un negocio de prueba no demo.
2. Completar una cita de ese negocio.
3. Comprobar que la cita se completa, no se crea una solicitud y la respuesta contiene `review_request_warning`.
4. Abrir el admin y comprobar el aviso: "Este negocio todavía no tiene enlace de reseñas configurado."

## D. Seed

1. Ejecutar `python -m app.seed`.
2. Consultar `GET /api/businesses` y comprobar que los tres negocios demo mantienen un `reviews_url`.
3. Comprobar que siguen existiendo sus servicios y `availability-settings`.
4. Confirmar que la limpieza elimina las solicitudes asociadas a reservas de prueba sin borrar datos demo estructurales.
