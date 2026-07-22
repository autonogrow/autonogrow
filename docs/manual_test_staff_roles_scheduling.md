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
2. En **Servicios que puede realizar**, asignar servicios distintos a cada miembro y guardar.
3. Definir horarios semanales distintos con **Editar horario**.
4. Abrir la landing: antes de elegir servicio no deben aparecer profesional ni calendario.
5. Elegir un servicio y comprobar que el selector incluye **Cualquiera disponible** y solo
   los profesionales asignados a ese servicio.
6. Elegir cada profesional y verificar que los dias y huecos cambian según su horario.
7. Cambiar de servicio: deben limpiarse profesional, día, hora y resumen.
8. Cambiar de profesional: deben limpiarse día y hora.
9. En un servicio sin profesionales, debe mostrarse el aviso correspondiente y bloquearse
   la confirmación, sin recurrir al horario general.
10. Forzar respuestas de error de calendario, huecos y reserva y comprobar que nunca aparece
    `[object Object]`.
11. Crear una reserva con profesional concreto y comprobar su nombre en el panel.
12. Crear una reserva con **Cualquiera disponible**. La asignacion usa, entre quienes
   admiten el hueco, el menor numero de reservas bloqueantes de ese dia y despues el id menor.
13. Intentar repetir el hueco para el mismo profesional: debe responder `409`.
14. Reservar el mismo horario con el segundo profesional: debe ser aceptado si sigue libre.
15. Desmarcar `bookable` o `show_schedule`: el miembro ya no debe aparecer publicamente.

## Compatibilidad

1. El arranque crea aditivamente `business_user_services`. Una migración registrada en
   `app_migrations` asigna una sola vez todos los servicios activos a los profesionales
   existentes que ya eran activos, reservables, visibles y no eliminados.
2. Los profesionales creados o reactivados después quedan sin servicios hasta que un
   `business_admin` los configure en **Equipo**.
3. En un negocio o servicio sin miembros públicos reservables, verificar que no aparece
   calendario y que no se usa la agenda general como fallback.
4. Comprobar que reservas antiguas sin profesional siguen visibles para administradores.
   Por seguridad, esas reservas bloquean el horario coincidente de todos los profesionales.
