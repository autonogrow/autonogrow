# Pruebas manuales: navegación del admin

## Preparación

1. Instalar dependencias con `.venv\Scripts\python.exe -m pip install -r backend\requirements.txt`.
2. Ejecutar la seed desde `backend` con `..\.venv\Scripts\python.exe -m app.seed`.
3. Iniciar el backend con `.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000`.
4. Servir el repositorio desde un origen permitido por CORS.
5. Abrir `autonogrow-admin/index.html?b=demo-barberia` y `autonogrow-landing/index.html?b=demo-barberia`.

## A. Navegación

1. Confirmar que aparecen las pestañas Resumen, Reservas, Mensajes WhatsApp, Servicios, Horarios, Datos del negocio y Reseñas.
2. Al abrir el admin, comprobar que Resumen es la única sección activa.
3. Recorrer todas las pestañas y verificar que solo se muestra la sección elegida.
4. Recargar con una sección seleccionada y comprobar que el hash de la URL permite conservarla.
5. En una pantalla móvil, comprobar que las pestañas tienen scroll horizontal y que ninguna tarjeta desborda el ancho.

## B. Resumen

1. Comparar las métricas de solicitudes, pendientes, confirmadas y completadas con Reservas.
2. Comparar las métricas de reseñas con la sección Reseñas.
3. Comparar mensajes pendientes, preparados y enviados con Mensajes WhatsApp.
4. Comprobar el número de servicios activos y el estado activo/inactivo del negocio.

## C. Datos del negocio y servicios

1. Editar titular o descripción, guardar y verificar el cambio en la landing.
2. Crear un servicio, editar precio y duración, y confirmar que aparece en la landing.
3. Desactivar el servicio y confirmar que queda atenuado en admin y oculto en la landing.
4. Actualizar el admin y comprobar que servicios y formularios no se duplican.

## D. Horarios

1. Confirmar que cada día muestra su nombre y el estado Abierto o Cerrado de forma separada.
2. En un día abierto, comprobar que los tramos aparecen debajo.
3. Marcar un día como Cerrado y verificar que desaparecen los tramos y aparece “Día cerrado”.
4. Volver a abrirlo, editar un tramo y guardar.
5. Crear y eliminar una excepción; actualizar y comprobar que no se duplica.

## E. Reservas y mensajes WhatsApp

1. Crear una cita desde la landing y verla una sola vez en Reservas.
2. Confirmarla, reagendarla y verificar que conserva la misma tarjeta e identificador.
3. Comprobar que confirmar, rechazar y completar siguen disponibles según el estado.
4. Verificar que las fotos adjuntas siguen visibles.
5. Abrir Mensajes WhatsApp y comprobar la solicitud o confirmación en “Pendientes y preparados”.
6. Marcar un mensaje como enviado u omitido y comprobar que pasa a “Historial enviados y omitidos”.
7. Probar el filtro sin resultados y esperar “No hay mensajes para este filtro.”

## F. Reseñas

1. Completar una cita de un negocio con Google Reviews URL.
2. Confirmar que la solicitud se muestra dentro de la reserva completada y en la sección Reseñas.
3. Comprobar cliente, número de cita, estado y mensaje.
4. Copiar el mensaje, marcarlo como enviado y verificar que pasa al historial.
5. Probar Omitir con otra solicitud.
6. Si no quedan solicitudes pendientes, esperar “No hay solicitudes de reseña pendientes.”

## G. Refresco y regresión

1. Pulsar Actualizar varias veces y cambiar entre todas las pestañas.
2. Confirmar que no se acumulan tarjetas de reservas, mensajes, servicios, excepciones ni reseñas.
3. Recargar el navegador y repetir la comprobación.
4. Verificar en la landing que negocio, servicios y reserva siguen funcionando.
