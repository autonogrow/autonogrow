# Prueba manual: roles y agenda por profesional

## Preparacion

- Desplegar primero el backend para que el arranque cree las columnas y tablas nuevas.
- Usar un negocio de prueba, dos cuentas de personal y un servicio activo.
- No ejecutar estas pruebas sobre reservas reales.

## Permisos

1. Entrar como owner y comprobar `/autonogrow-owner`.
2. Crear o reutilizar un negocio y asignar un `business_admin`.
3. Entrar en `/autonogrow-admin/?b=slug` como administrador.
4. En **Equipo**, añadir una cuenta `business_staff`.
5. Entrar como esa cuenta. Solo deben quedar visibles Resumen y Reservas.
6. Verificar que las peticiones directas `PATCH`/`POST` a settings, servicios,
   horarios generales, media y equipo responden `403`.
7. Confirmar que una cuenta sin asignar y una cuenta de otro negocio reciben `403`.
8. Asignar una reserva al miembro y comprobar que puede confirmarla, cancelarla,
   completarla, marcar no-show y guardar notas internas.
9. Intentar operar una reserva asignada a otro miembro mediante su id: debe responder `403`.

## Agenda por profesional

1. Como administrador, marcar dos miembros como activos, reservables y con horario visible.
2. Definir horarios semanales distintos con **Editar horario**.
3. Abrir la landing y comprobar el selector con **Cualquiera disponible** y ambos nombres.
4. Elegir cada profesional y verificar que los dias y huecos cambian según su horario.
5. Crear una reserva con profesional concreto y comprobar su nombre en el panel.
6. Crear una reserva con **Cualquiera disponible**. La asignacion usa, entre quienes
   admiten el hueco, el menor numero de reservas bloqueantes de ese dia y despues el id menor.
7. Intentar repetir el hueco para el mismo profesional: debe responder `409`.
8. Reservar el mismo horario con el segundo profesional: debe ser aceptado si sigue libre.
9. Desmarcar `bookable` o `show_schedule`: el miembro ya no debe aparecer publicamente.

## Compatibilidad

1. En un negocio sin miembros publicos reservables, verificar que no aparece selector y
   que se conserva la agenda general anterior.
2. Comprobar que reservas antiguas sin profesional siguen visibles para administradores.
   Por seguridad, esas reservas bloquean el horario coincidente de todos los profesionales.
