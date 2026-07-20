# Pruebas manuales: acciones directas de WhatsApp

## Preparación

1. Instalar dependencias con `.venv\Scripts\python.exe -m pip install -r backend\requirements.txt`.
2. Desde `backend`, ejecutar `..\.venv\Scripts\python.exe -m app.seed`.
3. Iniciar el backend en `http://127.0.0.1:8000` y servir el repositorio en `http://127.0.0.1:5500`.
4. Abrir `autonogrow-admin/index.html?b=demo-barberia` y `autonogrow-landing/index.html?b=demo-barberia`.
5. Permitir ventanas emergentes para el origen local durante esta prueba.

## A. Crear cita

1. Crear una cita desde la landing con el cliente `Cliente WhatsApp Sprint` y un teléfono internacional válido.
2. Confirmar que aparece en Reservas con estado Pendiente.
3. Consultar MessageOutbox por `booking_id` y comprobar que no existe `booking_requested`.

## B. Confirmar cita

1. Pulsar Confirmar en la tarjeta.
2. Confirmar que la cita cambia a `confirmed` y solo existe un `booking_confirmed`.
3. Comprobar que se abre WhatsApp con el mensaje preparado.
4. Confirmar que el outbox queda `opened`, no `sent`.
5. Usar “Marcar como enviado” únicamente después de enviar manualmente en WhatsApp.

## C. Próximo lunes

1. Crear una cita para el próximo lunes respecto a la fecha actual de Madrid.
2. Confirmarla y comprobar que el texto contiene `el próximo lunes a las HH:MM`.
3. Confirmar que no aparece una fecha numérica `DD/MM/YYYY`.

## D. Otro día

1. Crear una cita para un día que no sea el próximo lunes.
2. Confirmarla y comprobar un texto como `el martes 7 de julio a las HH:MM`.
3. Para una cita de otro año, comprobar que el año aparece al final.

## E. Completar cita

1. Pulsar Completada en una cita de un negocio con Google Reviews URL.
2. Confirmar que se crea una única ReviewRequest.
3. Confirmar que se crea un único `booking_completed_review` con el mismo mensaje.
4. Comprobar que WhatsApp se abre directamente y que el outbox queda `opened`.

## F. Sección Reseñas

1. Abrir Reseñas y comprobar que el botón principal dice “Enviar por WhatsApp”.
2. Pulsarlo y confirmar que reutiliza el mismo outbox, abre WhatsApp y lo deja `opened`.
3. Verificar que siguen disponibles “Marcar como enviada” y “Omitir”.

## G. Idempotencia

1. Repetir por API el cambio a `confirmed` y comprobar que sigue existiendo un solo `booking_confirmed`.
2. Repetir por API el cambio a `completed` y comprobar una sola ReviewRequest y un solo `booking_completed_review`.
3. Abrir dos veces un outbox pendiente/preparado y comprobar que conserva el mismo identificador.

## H. Teléfono inválido

1. Crear otra cita con teléfono vacío o inválido.
2. Confirmarla y comprobar que el estado cambia aunque WhatsApp no pueda abrirse.
3. Esperar el aviso `No se puede abrir WhatsApp porque el teléfono del cliente no es válido.`
4. Completarla y repetir la comprobación sin errores de estado ni duplicados.

## I. Rechazo, reagendado e historial

1. Rechazar una cita y comprobar que abre el mensaje `booking_rejected` si el teléfono es válido.
2. Reagendar otra cita y comprobar el mensaje `booking_rescheduled` con fecha natural.
3. Confirmar que Mensajes WhatsApp conserva pendientes, preparados, enviados y omitidos.
4. Los `booking_requested` históricos, si existen, deben aparecer solo en Historial y no contar en las métricas operativas.

## Limpieza

Ejecutar de nuevo la seed. El cliente `Cliente WhatsApp Sprint` y sus reservas, reseñas y mensajes asociados deben eliminarse.
