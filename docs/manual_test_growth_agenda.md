# Pruebas manuales: crecimiento diario y agenda

## Preparación

1. Desde `backend`, ejecutar `..\.venv\Scripts\python.exe -m app.seed`.
2. Iniciar backend en `http://127.0.0.1:8000` y servir el repositorio en `http://127.0.0.1:5500`.
3. Abrir `autonogrow-admin/index.html?b=demo-barberia` y la landing del mismo negocio.
4. Permitir ventanas emergentes para probar WhatsApp directo.

## A. Mensajes sin emojis

1. Crear y confirmar una cita nueva.
2. Comprobar que `booking_confirmed` empieza por `Hola {cliente},` y termina en `Te esperamos.`.
3. Rechazar y reagendar citas nuevas y comprobar que sus mensajes no contienen emojis.
4. Completar una cita y comprobar que la reseña empieza por `Gracias por venir hoy.`.
5. No usar mensajes históricos para esta prueba: no se migran ni reescriben.

## B. Pestaña Crecimiento

1. Confirmar que la navegación muestra Resumen, Crecimiento, Reservas, Mensajes WhatsApp, Servicios, Horarios, Datos del negocio y Reseñas.
2. Abrir Crecimiento y verificar título, subtítulo, barra, contador, porcentaje y puntos.
3. Comprobar cinco cards separadas: confirmar pendientes, enviar confirmaciones, completar citas de hoy, pedir reseña y dejar el día al día.
4. Confirmar que no aparecen tareas de configuración inicial.
5. Si no hay citas aplicables hoy, las tareas correspondientes deben mostrarse neutrales.

## C. Transiciones y animaciones

1. Con una cita pendiente, abrir Crecimiento y observar la tarea pendiente sin animación inicial.
2. Confirmar o rechazar la cita desde Reservas.
3. Volver a Crecimiento y comprobar el pulso, `Tarea completada` y `+10 puntos`.
4. Recargar o cambiar de pestaña varias veces: la animación no debe repetirse.
5. Revisar en localStorage la clave `autonogrow:growth:{slug}:{fecha}` con los ids celebrados.

## D. Día completado

1. Resolver solicitudes pendientes y preparar o enviar los mensajes importantes.
2. Completar una cita atendida hoy y abrir su solicitud de reseña.
3. Al completar todas las tareas aplicables, comprobar barra al 100% y el bloque `Día completado` / `Has dejado tu negocio al día.`.
4. Confirmar que la animación especial no se repite al renderizar de nuevo.

## E. Resumen

1. Abrir Resumen y comprobar la tarjeta `Crecimiento de hoy`.
2. Comparar su contador y barra con la pestaña Crecimiento.
3. Confirmar que muestra la siguiente tarea pendiente.
4. Pulsar `Ver tareas` y verificar que abre `#growth`.

## F. Agenda por vistas

1. Abrir Reservas y recorrer Pendientes, Hoy, Mañana, Próximas e Historial.
2. Pendientes debe contener solo estados `requested` o `pending`.
3. Hoy y Mañana deben contener citas activas de sus fechas.
4. Próximas debe contener citas activas posteriores a mañana.
5. Historial debe contener completadas, rechazadas, canceladas o citas pasadas no pendientes.
6. Comprobar los vacíos: `No hay citas pendientes.`, `No tienes citas para hoy.`, `No tienes citas para mañana.`, `No hay próximas citas.` y `Todavía no hay historial.`.

## G. Regresión

1. Crear, confirmar, reagendar, rechazar y completar citas.
2. Comprobar WhatsApp directo y el paso a `opened` sin marcar automáticamente como enviado.
3. Comprobar reseñas y MessageOutbox.
4. Pulsar Actualizar varias veces y verificar que no se duplican tareas ni reservas.
5. Confirmar que Servicios, Horarios, Datos del negocio y landing siguen funcionando.
