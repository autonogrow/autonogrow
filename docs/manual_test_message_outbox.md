# Pruebas manuales: cola de mensajes WhatsApp

## Preparación

1. Ejecutar `python -m app.seed` con `backend` en `PYTHONPATH`.
2. Iniciar el backend y abrir `autonogrow-admin/index.html?b=demo-barberia` desde un servidor local permitido por CORS.
3. Usar teléfonos de prueba en formato internacional, por ejemplo `+34 600 000 000`.

## A. Cita creada

1. Crear una cita desde la landing o `POST /api/businesses/demo-barberia/bookings`.
2. Consultar `GET /api/admin/businesses/demo-barberia/message-outbox?booking_id={id}`.
3. Comprobar que no se crea ningún mensaje `booking_requested` nuevo.
4. Si existen mensajes históricos de ese tipo, deben quedar relegados al Historial del admin.

## B. Cita confirmada

1. Marcar una cita solicitada como `confirmed`.
2. Comprobar un mensaje `booking_confirmed` con la fecha, hora y servicio correctos.
3. Repetir la confirmación y verificar que no aparece un segundo mensaje del mismo tipo.

## C. Cita rechazada

1. Marcar otra cita como `rejected`.
2. Comprobar un mensaje `booking_rejected`.
3. Consultar de nuevo los huecos del día y verificar que el horario rechazado vuelve a estar disponible.

## D. Cita reagendada

1. Reagendar una cita abierta a otro hueco.
2. Comprobar un mensaje `booking_rescheduled` cuyo snapshot contiene la nueva fecha y hora.
3. En este sprint solo se conserva el primer mensaje de reagendado por cita. Reagendados posteriores no crean otro mensaje.

## E. Cita completada

1. Completar una cita de un negocio con `reviews_url`.
2. Comprobar que se crean `ReviewRequest` y mensaje `booking_completed_review`.
3. Verificar que el texto del mensaje coincide con el snapshot de `ReviewRequest`.
4. Abrir WhatsApp desde la cola y confirmar manualmente el envío.

## F. Teléfono inválido

1. Crear una cita con teléfono `123` o sin teléfono.
2. Comprobar que el mensaje existe pero `whatsapp_url` es `null`.
3. Verificar en el admin el aviso "Este cliente no tiene un teléfono válido para WhatsApp."
4. Confirmar que el botón principal está deshabilitado y no se abre ninguna pestaña.

## G. No duplicados

1. Confirmar, rechazar o completar dos veces la misma cita.
2. Filtrar la cola por `booking_id`.
3. Comprobar que existe como máximo un mensaje por combinación de cita y `message_type`.

## Estados manuales

- `pending`: preparado, todavía no abierto.
- `opened`: se abrió WhatsApp; no implica que el cliente haya recibido el mensaje.
- `sent`: el negocio confirmó manualmente el envío.
- `skipped`: el negocio decidió omitirlo.
- `failed`: error marcado desde API.
